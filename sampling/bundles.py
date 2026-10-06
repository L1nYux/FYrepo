"""核验并导入 FYrepo / sample-llm 原生结果包，不补造研究数据。"""
import csv
import io
import json
import re
import zipfile
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import CandidatePaper, SamplingArtifact, SamplingRun
from .scope import PERIOD_MAP, tier_for
from .services import (SamplingError, _artifact_save, _canonical_sha, _decode_bytes,
                       _rank_candidates, normalize_record, sha256_bytes, sha256_text)

INT_FRAME = ('start_year', 'end_year', 'target_n', 'reserve_n', 'cross_disciplinary_journal', 'frame_order')
ARTIFACTS = {
    'sampling_frame.csv': 'frame', 'candidate_registry.csv': 'registry',
    'sampling_protocol.json': 'protocol', 'SAMPLING_PROTOCOL.md': 'protocol_md',
    'sampling_certificate.csv': 'certificate', 'sampling_ranking_full.csv': 'ranking',
    'selected_samples.csv': 'selected', 'reserve_samples.csv': 'reserve',
    'sampling_issues.csv': 'issues', 'download_queue.csv': 'download_queue',
    'evidence_queue.csv': 'evidence_queue', 'safe_sample_manifest.csv': 'safe_manifest',
    'labels_vault_seed_DO_NOT_COMMIT.csv': 'labels_seed',
}


def _rows(payload):
    return list(csv.DictReader(io.StringIO(_decode_bytes(payload))))


def _csv_hash(payload):
    # sample-llm exporter._frame_fingerprint：排序列、稳定排序行、UTF-8 CSV。
    rows = _rows(payload)
    if not rows:
        return sha256_bytes(b'')
    fields = sorted(rows[0])
    order = [f for f in ('stratum_id','candidate_key','paper_id','title') if f in fields]
    rows.sort(key=lambda row: tuple(row[f] for f in order))
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fields, lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return sha256_text(text.getvalue())


def _verify_selection(run, frame, selected, ranking):
    pools, used, expected, expected_audit = {}, set(), {}, []
    for paper in run.candidates.filter(decision='include'):
        pools.setdefault(paper.stratum_id, []).append(paper)
    counters = {'MAIN': 1, 'HOLDOUT': 1, 'RESERVE': 1}
    for role in ('MAIN', 'HOLDOUT', 'RESERVE'):
        for fr in frame:
            if role != 'RESERVE' and fr['role'] != role:
                continue
            n = fr['reserve_n'] if role == 'RESERVE' else fr['target_n']
            if role == 'RESERVE' and n == 0:
                continue
            pool = [p for p in pools.get(fr['stratum_id'], []) if p.candidate_key not in used]
            seed = run.sampling_seed + ('|reserve' if role == 'RESERVE' else '')
            ranked = _rank_candidates(pool, seed, fr['stratum_id'], run.sampling_method)
            if role != 'RESERVE' and len(ranked) < n:
                raise SamplingError('结果包存在主样本或留出样本缺口，请补足候选池后重新冻结。')
            picked = {}
            for row in ranked[:n]:
                pid = f"{dict(MAIN='P', HOLDOUT='H', RESERVE='R')[role]}{counters[role]:03d}"
                expected[pid] = (row['obj'].candidate_key, role, row['draw_hash'], row['draw_rank'])
                picked[row['obj'].candidate_key] = pid
                used.add(row['obj'].candidate_key); counters[role] += 1
            for row in ranked:
                key = row['obj'].candidate_key
                expected_audit.append((role + '_DRAW', fr['stratum_id'], key, row['draw_hash'],
                    row['draw_rank'], len(ranked), int(key in picked), picked.get(key, '')))
    actual = {}
    for row in selected:
        pid = row.get('paper_id', '')
        if pid in actual or not re.fullmatch('[PHR][0-9]+', pid):
            raise SamplingError('结果包中的样本编号重复或无效。')
        actual[pid] = (row['candidate_key'], row['sample_role'], row['draw_hash'], int(row['draw_rank']))
        paper = run.candidates.filter(candidate_key=row['candidate_key']).first()
        if paper is None:
            raise SamplingError('选中论文不在结果包的候选池中。')
        for field in ('title', 'journal', 'tier', 'period', 'stratum_id'):
            if row.get(field) != getattr(paper, field):
                raise SamplingError('选中结果的论文元信息与候选池不一致。')
    if actual != expected:
        raise SamplingError('选中结果与候选池、Seed 的确定性抽样结果不一致，拒绝导入。')
    actual_audit = [(r['sampling_stage'], r['stratum_id'], r['candidate_key'], r['draw_hash'],
                    int(r['draw_rank']), int(r['pool_size']), int(r['selected']), r['paper_id']) for r in ranking]
    if sorted(actual_audit) != sorted(expected_audit):
        raise SamplingError('结果包完整排序记录与实际候选池、抽样选择不一致。')


@transaction.atomic
def import_bundle(project, uploaded_file, user, name='', version='imported'):
    try:
        data = uploaded_file.read(40 * 1024 * 1024 + 1)
        if len(data) > 40 * 1024 * 1024:
            raise SamplingError('结果包不能超过 40 MB。')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(f.file_size for f in entries) > 80 * 1024 * 1024:
                raise SamplingError('结果包内容过大，解压总量上限为 80 MB。')
            if len({f.filename for f in entries}) != len(entries):
                raise SamplingError('结果包含重复文件名。')
            names = set(archive.namelist())
            required = {'sampling_protocol.json','sampling_frame.csv','candidate_registry.csv',
                        'selected_samples.csv','reserve_samples.csv','sampling_certificate.csv','sampling_ranking_full.csv'}
            if required - names:
                raise SamplingError('结果包缺少：' + '、'.join(sorted(required - names)))
            files = {n:archive.read(n) for n in ARTIFACTS if n in names}
        protocol = json.loads(_decode_bytes(files['sampling_protocol.json']))
        if not isinstance(protocol, dict):
            raise SamplingError('结果包协议须为 JSON 对象。')
        if protocol.get('protocol_version') != 'sampling_protocol_v1':
            raise SamplingError('不支持该抽样协议版本。')
        frame = _rows(files['sampling_frame.csv']); registry = _rows(files['candidate_registry.csv'])
        if not frame or not registry:
            raise SamplingError('结果包抽样框和候选池不能为空。')
        for fr in frame:
            for f in INT_FRAME:
                fr[f] = int(fr[f])
            if fr['role'] not in ('MAIN','HOLDOUT') or fr['target_n'] < 1 or fr['reserve_n'] < 0:
                raise SamplingError('结果包抽样参数无效。')
            period = PERIOD_MAP.get(fr['period'])
            if fr['role'] == 'MAIN' and (not period or fr['start_year'] != period['start_year'] or fr['end_year'] != period['end_year']):
                raise SamplingError('结果包研究时期与正式目录不一致。')
            if fr['role'] == 'HOLDOUT' and fr['period'] != 'HOLDOUT':
                raise SamplingError('留出样本时期标记无效。')
            if fr['tier'] != tier_for(fr['journal_family_name'], fr['period'] if period else 'P3'):
                raise SamplingError('结果包期刊层级与研究时期不匹配。')
        if len({fr['stratum_id'] for fr in frame}) != len(frame) or len({(fr['journal_family_name'],fr['period']) for fr in frame}) != len(frame):
            raise SamplingError('结果包存在重复抽样格。')
        frame.sort(key=lambda fr: fr['frame_order'])
        if protocol.get('hash_format') == 'canonical_json_v1':
            for row in registry:
                row['year'] = int(row['year']) if row['year'] else None
                if 'cross_disciplinary_journal' in row:
                    row['cross_disciplinary_journal'] = row['cross_disciplinary_journal'] in ('True','1','true')
            hashes = (_canonical_sha(frame), _canonical_sha(registry))
        else:
            hashes = (_csv_hash(files['sampling_frame.csv']), _csv_hash(files['candidate_registry.csv']))
        if hashes != (protocol.get('sampling_frame_sha256'), protocol.get('candidate_registry_sha256')):
            raise SamplingError('结果包文件 SHA256 与协议不一致，可能已被修改。')
        fingerprint = sha256_text('|'.join([protocol['protocol_version'], protocol['method'], protocol['seed'], *hashes]))
        if fingerprint != protocol.get('run_fingerprint'):
            raise SamplingError('结果包运行指纹不一致。')
        main = [fr for fr in frame if fr['role'] == 'MAIN']; hold = [fr for fr in frame if fr['role'] == 'HOLDOUT']
        if not main or len({fr['target_n'] for fr in main}) != 1 or len({fr['reserve_n'] for fr in frame}) != 1:
            raise SamplingError('当前工作台要求主抽样格数量和备用数量各自统一。')
        if hold and len({(fr['target_n'],fr['start_year'],fr['end_year']) for fr in hold}) != 1:
            raise SamplingError('结果包留出参数不统一。')
        periods = [dict(PERIOD_MAP[p]) for p in dict.fromkeys(fr['period'] for fr in main)]
        # 在完整验证之前保持草稿；任何失败均回滚数据库。
        run = SamplingRun.objects.create(project=project, name=name or f'导入样本集 {timezone.now():%Y%m%d-%H%M}',
            version=version, periods=periods, selected_tiers=list(dict.fromkeys(fr['tier'] for fr in frame)),
            selected_journals=list(dict.fromkeys(fr['journal_family_name'] for fr in frame)),
            main_n=main[0]['target_n'], reserve_n=main[0]['reserve_n'], holdout_enabled=bool(hold),
            holdout_n=hold[0]['target_n'] if hold else 1, holdout_start=hold[0]['start_year'] if hold else None,
            holdout_end=hold[0]['end_year'] if hold else None, sampling_method=protocol['method'],
            sampling_seed=protocol['seed'], created_by=user)
        chosen = _rows(files['selected_samples.csv']) + _rows(files['reserve_samples.csv'])
        selected_map = {row['candidate_key']:row for row in chosen}
        if len(selected_map) != len(chosen):
            raise SamplingError('结果包重复选择了同一论文。')
        strata = {fr['stratum_id']:fr for fr in frame}
        keys = set()
        for row in registry:
            rec = normalize_record(row)
            key = row['candidate_key']
            if key in keys or not key or not rec['title']:
                raise SamplingError('候选池稳定键重复、为空或缺少题名。')
            keys.add(key)
            sel = selected_map.get(key, {})
            fr = strata.get(row.get('stratum_id'))
            if row.get('decision') == 'include' and not fr:
                raise SamplingError('被纳入的候选论文不属于任何抽样格。')
            if fr and (rec['year'] is None or not fr['start_year'] <= rec['year'] <= fr['end_year'] or row.get('journal_family_name') != fr['journal_family_name']):
                raise SamplingError('候选论文与其抽样格时期或期刊不一致。')
            if row.get('eligibility_status') == 'UNCERTAIN' and row.get('decision') not in ('include','exclude'):
                raise SamplingError('结果包仍有未完成人工复核的论文。')
            paper = CandidatePaper(run=run, candidate_key=key, **{f:rec[f] for f in
                ('title','authors','journal','year','issue','volume','doi','cnki_dbcode','cnki_filename','keywords','abstract','clc','article_type')},
                cnki_url=rec['url'], stratum_id=row.get('stratum_id',''), period=row.get('period',''), tier=row.get('tier',''),
                journal_family_name=row.get('journal_family_name',''), frame_match_status=row.get('frame_match_status',''),
                cross_disciplinary_journal=bool(fr and fr['cross_disciplinary_journal']),
                eligibility_status=row['eligibility_status'], eligibility_reason=row.get('eligibility_reason',''), decision=row['decision'],
                sample_role=sel.get('sample_role',''), paper_id=sel.get('paper_id',''), draw_hash=sel.get('draw_hash',''),
                draw_rank=int(sel['draw_rank']) if sel else None,
                stratum_pool_size=int(sel['stratum_pool_size']) if sel.get('stratum_pool_size') else None,
                reserve_rank=int(sel['reserve_rank']) if sel.get('reserve_rank') else None, reserve_for_role=sel.get('reserve_for_role',''),
                source_file=Path(uploaded_file.name).name[:300])
            paper.full_clean(); paper.save()
        _verify_selection(run, frame, chosen, _rows(files['sampling_ranking_full.csv']))
        certificate = _rows(files['sampling_certificate.csv'])
        if {(r['paper_id'],r['candidate_key'],r['draw_hash']) for r in certificate} != {(r['paper_id'],r['candidate_key'],r['draw_hash']) for r in chosen}:
            raise SamplingError('结果包抽样凭证与选中论文不一致。')
        if len(certificate) != len(chosen) or any(r.get('run_fingerprint') != fingerprint or
            r.get('protocol_version') != protocol['protocol_version'] or
            r.get('sampling_method') != protocol['method'] or
            r.get('sampling_seed') != protocol['seed'] + ('|reserve' if r.get('sample_role') == 'RESERVE' else '')
            for r in certificate):
            raise SamplingError('抽样凭证的指纹、方法、版本或 Seed 不一致。')
        protocol['frame_snapshot'] = frame
        run.protocol = protocol; run.protocol_version = protocol['protocol_version']
        run.sampling_frame_sha256, run.candidate_registry_sha256 = hashes
        run.run_fingerprint = fingerprint; run.status = SamplingRun.FROZEN; run.frozen_at = timezone.now(); run.save()
        for filename, payload in files.items():
            _artifact_save(run, ARTIFACTS[filename], filename, payload)
        _artifact_save(run, SamplingArtifact.TYPE_BUNDLE, Path(uploaded_file.name).name, data)
        return run
    except SamplingError:
        raise
    except (ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile, OSError, RuntimeError, ValidationError) as exc:
        raise SamplingError('结果包格式或数据校验失败，请从采集工具重新导出完整结果包。') from exc
