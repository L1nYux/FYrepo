from __future__ import annotations
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile
import zlib
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from .models import CandidatePaper, SamplingDocument, SamplingRun
from .services import SamplingError, _csv_bytes

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_ZIP_BYTES = 40 * 1024 * 1024
CONVERTER_VERSION = 'fyrepo-pdfplumber-v2'


@transaction.atomic
def store_pdf(run, paper_id, original_name, data, user, *, queue=True):
    run = SamplingRun.objects.select_for_update().get(pk=run.pk)
    if not run.is_frozen:
        raise SamplingError('请先冻结抽样，全文才能绑定正式样本编号。')
    paper = run.candidates.filter(paper_id=paper_id).exclude(paper_id='').first()
    if not paper:
        raise SamplingError('样本编号不属于当前冻结版本。')
    name = Path(original_name.replace('\\', '/')).name
    if not name.lower().endswith('.pdf') or b'%PDF-' not in data[:1024]:
        raise SamplingError('请选择真实 PDF 文件；不支持 CAJ、HTML 或仅修改扩展名的文件。')
    if not data or len(data) > MAX_PDF_BYTES:
        raise SamplingError('单份 PDF 不能超过 20 MB。')
    sha = hashlib.sha256(data).hexdigest()
    existing = paper.documents.filter(pdf_sha256=sha).first()
    if existing:
        return existing, False
    doc = SamplingDocument(candidate=paper, original_name=name[:255], pdf_sha256=sha,
                           status=SamplingDocument.QUEUED if queue else SamplingDocument.RECEIVED,
                           uploaded_by=user)
    doc.pdf_file.save(name, ContentFile(data), save=False)
    doc.save()
    paper.pdf_status = '已接收'
    paper.md_status = '等待转换' if queue else '待转换'
    paper.save(update_fields=['pdf_status', 'md_status', 'updated_at'])
    return doc, True


def store_upload(run, file, paper_id, user):
    if file.name.lower().endswith('.pdf'):
        if file.size > MAX_PDF_BYTES:
            raise SamplingError('单份 PDF 不能超过 20 MB。')
        doc, created = store_pdf(run, paper_id, file.name, file.read(), user)
        return [doc], int(created)
    if not file.name.lower().endswith('.zip') or file.size > MAX_ZIP_BYTES:
        raise SamplingError('请上传 PDF，或不超过 40 MB 的全文 ZIP。')
    try:
        with zipfile.ZipFile(file) as archive:
            infos = archive.infolist()
            if len(infos) > 200 or sum(x.file_size for x in infos) > 80 * 1024 * 1024:
                raise SamplingError('全文包最多 100 份 PDF，解压总量不能超过 80 MB。')
            if len({x.filename for x in infos}) != len(infos):
                raise SamplingError('全文包存在重复文件名。')
            mapping = list(csv.DictReader(io.StringIO(archive.read('pdf_manifest.csv').decode('utf-8-sig'))))
            if not mapping or len(mapping) > 100:
                raise SamplingError('pdf_manifest.csv 须含 1–100 行 paper_id、source_pdf 映射。')
            valid_ids = set(run.candidates.exclude(paper_id='').values_list('paper_id', flat=True))
            prepared, seen = [], set()
            for row in mapping:
                pid, name = (row.get('paper_id') or '').strip(), (row.get('source_pdf') or '').strip()
                if pid not in valid_ids or pid in seen or not name or Path(name).is_absolute() or '..' in Path(name).parts:
                    raise SamplingError('全文映射含无效编号、重复编号或无效路径。')
                info = archive.getinfo(name)
                if info.file_size > MAX_PDF_BYTES:
                    raise SamplingError(f'{name} 超过单份 20 MB 限制。')
                data = archive.read(name)
                if b'%PDF-' not in data[:1024] or not name.lower().endswith('.pdf'):
                    raise SamplingError(f'{name} 不是有效 PDF 文件。')
                prepared.append((pid, name, data)); seen.add(pid)
    except (zipfile.BadZipFile, zlib.error, KeyError, UnicodeError, RuntimeError, OSError) as exc:
        raise SamplingError('全文包无法读取：须包含 pdf_manifest.csv 和其引用的原始 PDF。') from exc
    # 校验完整包后再保存；业务数据库写入保持原子性。
    docs, created = [], 0
    with transaction.atomic():
        for pid, name, data in prepared:
            doc, is_new = store_pdf(run, pid, name, data, user)
            docs.append(doc); created += int(is_new)
    return docs, created


def latest_documents(run):
    docs, seen = [], set()
    for doc in SamplingDocument.objects.filter(candidate__run=run).select_related('candidate').order_by('-created_at', '-pk'):
        if doc.candidate_id not in seen:
            seen.add(doc.candidate_id); docs.append(doc)
    return docs


def enqueue_documents(run):
    count = 0
    for doc in latest_documents(run):
        if doc.status in (SamplingDocument.RECEIVED, SamplingDocument.FAILED):
            changed = SamplingDocument.objects.filter(pk=doc.pk, status=doc.status).update(status=SamplingDocument.QUEUED, error='', claim_token='')
            if changed:
                CandidatePaper.objects.filter(pk=doc.candidate_id).update(md_status='等待转换')
            count += changed
    return count


def process_next_document(*, timeout=300):
    """跨进程 CAS 领取；耗时转换在子进程，超过时限或 worker 重启可恢复。"""
    doc = SamplingDocument.objects.filter(status=SamplingDocument.QUEUED).order_by('created_at', 'pk').first()
    if not doc:
        return None
    claim = uuid.uuid4().hex
    changed = SamplingDocument.objects.filter(pk=doc.pk, status=SamplingDocument.QUEUED).update(
        status=SamplingDocument.RUNNING, claim_token=claim, started_at=timezone.now(), completed_at=None)
    if not changed:
        return None
    doc.refresh_from_db()
    paper = doc.candidate
    CandidatePaper.objects.filter(pk=paper.pk).update(md_status='正在转换')
    updates = {'completed_at': timezone.now(), 'converter_version': CONVERTER_VERSION}
    md_data = None
    try:
        with tempfile.TemporaryDirectory(prefix='fyrepo-pdf-') as temp:
            root = Path(temp)
            source = root / 'source.pdf'
            with doc.pdf_file.open('rb') as f:
                source.write_bytes(f.read())
            config = {'pdf': str(source), 'output': str(root), 'paper_id': paper.paper_id,
                      'source_name': doc.original_name, 'result': str(root / 'result.json'),
                      'metadata': {'title': paper.title, 'authors': paper.authors, 'journal': paper.journal, 'doi': paper.doi}}
            spec = root / 'spec.json'; spec.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            subprocess.run([sys.executable, '-m', 'sampling.converters.runner', str(spec)],
                           cwd=settings.BASE_DIR, check=True, timeout=timeout, capture_output=True)
            result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
            if result['status'] != '成功':
                raise SamplingError(result.get('error') or '转换失败')
            md_data = (root / f'{paper.paper_id}.md').read_bytes()
            warnings = [x for x in result['warnings'].split('；') if x]
            updates.update(status=SamplingDocument.REVIEW if warnings else SamplingDocument.READY,
                           pages=result['pages'], characters=result['characters'], warnings=warnings,
                           md_sha256=hashlib.sha256(md_data).hexdigest(), error='')
    except subprocess.TimeoutExpired:
        updates.update(status=SamplingDocument.FAILED, error='转换超过 300 秒，已停止。请检查 PDF，必要时先完成 OCR 后重新上传。')
    except Exception as exc:
        updates.update(status=SamplingDocument.FAILED, error=str(exc)[:1200])
    updates['completed_at'] = timezone.now()
    with transaction.atomic():
        current = SamplingDocument.objects.select_for_update().get(pk=doc.pk)
        if current.status != SamplingDocument.RUNNING or current.claim_token != claim:
            return current
        if md_data is not None:
            current.md_file.save(f'{paper.paper_id}.md', ContentFile(md_data), save=False)
            updates['md_file'] = current.md_file.name
        SamplingDocument.objects.filter(pk=doc.pk).update(**updates)
        if paper.documents.order_by('-created_at', '-pk').first().pk == doc.pk:
            CandidatePaper.objects.filter(pk=paper.pk).update(md_status=dict(SamplingDocument.STATUS_CHOICES)[updates['status']])
    doc.refresh_from_db()
    return doc


def recover_abandoned_documents():
    # 子进程最长 300 秒；留出宽裕窗口后才标为失败，避免抢走活跃任务。
    cutoff = timezone.now() - timedelta(minutes=15)
    stale = SamplingDocument.objects.filter(status=SamplingDocument.RUNNING, started_at__lt=cutoff)
    ids = set(stale.values_list('pk', flat=True))
    count = stale.update(status=SamplingDocument.FAILED, error='转换进程中断，可点击重试', claim_token='')
    for doc in SamplingDocument.objects.filter(pk__in=ids).select_related('candidate'):
        if doc.candidate.documents.order_by('-created_at', '-pk').first().pk == doc.pk:
            CandidatePaper.objects.filter(pk=doc.candidate_id).update(md_status='转换失败')
    return count


def document_bundle(run):
    """Canonical MD 包含真实元信息；尚未匿名化。原 PDF 与编号独立映射。"""
    fields = ['paper_id', 'sample_role', 'source_pdf', 'pdf_sha256', 'md_file', 'md_sha256',
              'status', 'pages', 'characters', 'warnings', 'error', 'converter_version', 'run_fingerprint']
    rows, data = [], io.BytesIO()
    latest = {d.candidate_id: d for d in latest_documents(run)}
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in run.candidates.exclude(paper_id='').order_by('paper_id'):
            doc = latest.get(p.pk)
            if not doc:
                rows.append({'paper_id': p.paper_id, 'sample_role': p.sample_role, 'status': p.pdf_status,
                             'run_fingerprint': run.run_fingerprint})
                continue
            row = {'paper_id': p.paper_id, 'sample_role': p.sample_role, 'source_pdf': doc.original_name,
                   'pdf_sha256': doc.pdf_sha256, 'md_file': f'{p.paper_id}.md' if doc.md_file else '',
                   'md_sha256': doc.md_sha256, 'status': doc.get_status_display(), 'pages': doc.pages,
                   'characters': doc.characters, 'warnings': '；'.join(doc.warnings), 'error': doc.error,
                   'converter_version': doc.converter_version, 'run_fingerprint': run.run_fingerprint}
            rows.append(row)
            if doc.md_file:
                with doc.md_file.open('rb') as stream:
                    archive.writestr(f'markdown/{p.paper_id}.md', stream.read())
        archive.writestr('pdf_md_manifest.csv', _csv_bytes(fields, rows))
        archive.writestr('README.txt', 'Canonical Markdown 含真实题名和作者；尚未匿名化。\n原 PDF 文件名未修改，映射见 pdf_md_manifest.csv。\n转换有警告或失败的文件需人工复核。\n')
    return data.getvalue()
