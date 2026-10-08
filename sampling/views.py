from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import permissions as perms
from core.models import Experiment

from .forms import CandidateUploadForm, ResultBundleImportForm, SamplingRunForm
from .models import CandidatePaper, SamplingArtifact, SamplingExperimentLink, SamplingRun, SamplingDocument
from .services import (
    SamplingError, SamplingShortage, collection_config, freeze_run,
    import_result_bundle, ingest_records, ingest_uploaded_file, refresh_run_status,
    update_review_decisions, build_frame, freeze_readiness,
)


def _require_authenticated(request):
    if not request.user.is_authenticated or not request.user.is_active:
        raise PermissionDenied("请先登录。")


def _run(request, pk):
    return get_object_or_404(
        _visible_runs(request).select_related("project", "created_by"),
        pk=pk,
        archived_at__isnull=True,
    )


def _can_manage(request, run):
    return bool(
        perms.is_admin(request)
        or (run.project_id and perms.can_manage_project(request, run.project))
        or run.created_by_id == request.user.pk
    )


def _require_manage(request, run):
    _require_authenticated(request)
    if not _can_manage(request, run):
        raise PermissionDenied("只有管理员、项目负责人或样本集创建者可以修改该样本集。")


def _visible_runs(request):
    _require_authenticated(request)
    from core.resource_navigation import spaces
    visible = spaces(request.user)
    if request.GET.get('ownership') not in (None, 'all'):
        visible = visible.filter(pk=request.workspace.pk)
    return SamplingRun.objects.filter(workspace__in=visible, archived_at__isnull=True).select_related(
        "project", "created_by", "workspace__team", "workspace__owner"
    )


def _next_version(version):
    match = re.fullmatch(r"v(\d+)", (version or "").strip(), re.I)
    if match:
        return f"v{int(match.group(1)) + 1}"
    return f"{version or 'v1'}-new"


def _index_page(request, form=None, drawer_open=False, bundle_form=None):
    runs = _visible_runs(request).annotate(candidate_total=Count("candidates", distinct=True))
    from .scope import REGISTRY
    return render(request, "sampling/index.html", {
        "shell_section": "样本库", "runs": runs,
        "bundle_form": bundle_form or ResultBundleImportForm(viewer=request),
        "scope_form": form if form is not None else SamplingRunForm(viewer=request),
        "drawer_open": drawer_open, "scope_title": "新建样本集", "scope_action": "sampling:new",
        "journal_registry": REGISTRY,
    })


@login_required
def index(request):
    return _index_page(request)


@login_required
def run_new(request):
    _require_authenticated(request)
    form = SamplingRunForm(request.POST if request.method == "POST" else None, viewer=request)
    if request.method == "POST" and form.is_valid():
        run = form.save(commit=False)
        run.created_by = request.user
        run.save()
        messages.success(request, "样本集已创建。请采集或导入真实候选题录。")
        return redirect("sampling:detail", pk=run.pk)
    return _index_page(request, form=form, drawer_open=True)


@login_required
@transaction.atomic
def run_edit(request, pk):
    run = get_object_or_404(_visible_runs(request).select_for_update().select_related("project"),
                            pk=pk, archived_at__isnull=True)
    _require_manage(request, run)
    if run.is_frozen:
        messages.error(request, "已冻结样本集不可直接修改；请创建新版本。")
        return redirect("sampling:detail", pk=run.pk)
    form = SamplingRunForm(request.POST if request.method == "POST" else None, instance=run, viewer=request)
    if request.method == "POST" and form.is_valid():
        scope_fields = {"periods", "selected_tiers", "selected_journals", "main_n", "reserve_n",
                        "holdout_enabled", "holdout_start", "holdout_end", "holdout_n",
                        "sampling_method", "sampling_seed"}
        changed = bool({'periods', 'selected_tiers', 'selected_journals', 'holdout_enabled',
                        'holdout_start', 'holdout_end'} & set(form.changed_data))
        form.save()
        if changed:
            count = run.candidates.count()
            run.candidates.all().delete()
            run.status = SamplingRun.DRAFT
            run.save(update_fields=["status", "updated_at"])
            if count:
                messages.warning(request, f"研究范围已更新，原 {count} 篇候选题录已清空，请按新范围重新采集或导入。")
        messages.success(request, "研究范围已保存。")
        return redirect("sampling:detail", pk=run.pk)
    return detail(request, pk, scope_form=form, drawer_open=True)


@login_required
@require_POST
@transaction.atomic
def run_clone(request, pk):
    source = get_object_or_404(_visible_runs(request).select_for_update(), pk=pk, archived_at__isnull=True)
    _require_manage(request, source)
    version = _next_version(source.version)
    while SamplingRun.objects.filter(workspace=source.workspace, name=source.name, project=source.project, version=version).exists():
        version = _next_version(version)
    clone = SamplingRun.objects.create(
        workspace=source.workspace,
        project=source.project,
        name=source.name,
        version=version,
        source_run=source,
        periods=source.periods,
        selected_tiers=source.selected_tiers,
        selected_journals=source.selected_journals,
        main_n=source.main_n,
        reserve_n=source.reserve_n,
        holdout_enabled=source.holdout_enabled,
        holdout_start=source.holdout_start,
        holdout_end=source.holdout_end,
        holdout_n=source.holdout_n,
        sampling_method=source.sampling_method,
        sampling_seed=source.sampling_seed,
        status=SamplingRun.DRAFT,
        created_by=request.user,
    )
    messages.success(request, f"已创建新版本 {clone.version}。原冻结版本保持不变。")
    return redirect("sampling:edit", pk=clone.pk)


@login_required
def detail(request, pk, scope_form=None, drawer_open=False):
    run = _run(request, pk)
    _require_authenticated(request)
    refresh_run_status(run)

    q = (request.GET.get("q") or "").strip()
    tier = (request.GET.get("tier") or "").strip()
    period = (request.GET.get("period") or "").strip()
    state = (request.GET.get("state") or "").strip()

    candidates = run.candidates.all()
    if q:
        candidates = candidates.filter(Q(title__icontains=q) | Q(journal__icontains=q))
    if tier:
        candidates = candidates.filter(tier=tier)
    if period:
        candidates = candidates.filter(period=period)
    if state:
        candidates = candidates.filter(eligibility_status=state)
    candidate_page = Paginator(candidates, 100).get_page(request.GET.get("page"))

    review_queryset = run.candidates.filter(
        eligibility_status=CandidatePaper.UNCERTAIN,
        decision=CandidatePaper.PENDING,
    ).order_by("journal", "year", "issue", "title")

    selected = run.candidates.exclude(sample_role="").order_by("paper_id")
    counts = {
        "candidate": run.candidates.count(),
        "eligible": run.candidates.filter(decision=CandidatePaper.INCLUDE).count(),
        "review": review_queryset.count(),
        "main": run.candidates.filter(sample_role=CandidatePaper.ROLE_MAIN).count(),
        "holdout": run.candidates.filter(sample_role=CandidatePaper.ROLE_HOLDOUT).count(),
        "reserve": run.candidates.filter(sample_role=CandidatePaper.ROLE_RESERVE).count(),
    }

    frame = build_frame(run)
    frame_rows = []
    for p in run.periods + ([{"id": "HOLDOUT", "start_year": run.holdout_start, "end_year": run.holdout_end}] if run.holdout_enabled else []):
        rows = [r for r in frame if r["period"] == p["id"]]
        frame_rows.append({"period": p["id"], "years": f"{p['start_year']}–{p['end_year']}",
                           "tiers": " · ".join(sorted({r["tier"] for r in rows})),
                           "journals": len(rows), "main_target": sum(r["target_n"] for r in rows)})
    artifacts = list(run.artifacts.all())
    edit_form = scope_form if scope_form is not None else (SamplingRunForm(instance=run, viewer=request) if not run.is_frozen else None)
    from .scope import REGISTRY
    documents = list(run.candidates.exclude(paper_id="").prefetch_related("documents").order_by("paper_id"))
    for paper in documents:
        paper.latest_document = next(iter(paper.documents.all()), None)
    readiness = freeze_readiness(run)
    upload_form = CandidateUploadForm()

    return render(request, "sampling/detail.html", {
        "shell_section": "样本库",
        "run": run,
        "counts": counts,
        "frame_rows": frame_rows,
        "candidate_page": candidate_page,
        "review_items": Paginator(review_queryset, 100).get_page(request.GET.get('review_page')),
        "selected": selected,
        "artifacts": artifacts,
        "can_manage": _can_manage(request, run),
        "scope_form": edit_form, "drawer_open": drawer_open, "scope_title": "编辑研究范围",
        "journal_registry": REGISTRY, "readiness": readiness, "document_papers": documents,
        "document_processing": any(p.latest_document and p.latest_document.status in ("queued", "running") for p in documents),
        "upload_form": upload_form,
        "agent_origin": getattr(settings, "SAMPLING_AGENT_ORIGIN", "http://127.0.0.1:8765"),
        "filter_values": {"q": q, "tier": tier, "period": period, "state": state},
    })


@login_required
@require_POST
def candidate_import(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    if run.is_frozen:
        raise PermissionDenied("已冻结样本集不可导入候选论文。")
    form = CandidateUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "请选择有效题录文件。")
        return redirect("sampling:detail", pk=run.pk)
    try:
        result = ingest_uploaded_file(run, form.cleaned_data["file"])
        messages.success(
            request,
            f"候选题录导入完成：新增 {result['created']}，更新 {result['updated']}，"
            f"当前候选池 {result['total']} 篇。"
        )
    except SamplingError as exc:
        messages.error(request, str(exc))
    return redirect("sampling:detail", pk=run.pk)


@login_required
@require_POST
def review_apply(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    ids = [
        int(x) for x in request.POST.getlist("candidate_ids")
        if str(x).isdigit()
    ]
    action = request.POST.get("action", "")
    if not ids:
        messages.error(request, "请至少勾选一篇待复核论文。")
        return redirect("sampling:detail", pk=run.pk)
    try:
        count = update_review_decisions(run, ids, action)
        label = "选入" if action == CandidatePaper.INCLUDE else "排除"
        messages.success(request, f"已将 {count} 篇论文设为“{label}”。")
    except SamplingError as exc:
        messages.error(request, str(exc))
    return redirect("sampling:detail", pk=run.pk)


@login_required
@require_POST
def run_freeze(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    try:
        result = freeze_run(run)
        if result["issues"]:
            messages.warning(request, "样本已冻结，但部分抽样格备用样本不足；请查看抽样问题文件。")
        else:
            messages.success(request, "样本已冻结，抽样凭证与交付文件已生成。")
    except SamplingShortage as exc:
        messages.error(request, str(exc))
    except SamplingError as exc:
        messages.error(request, str(exc))
    return redirect("sampling:detail", pk=run.pk)


@login_required
def artifact_download(request, pk, artifact_pk):
    run = _run(request, pk)
    _require_authenticated(request)
    artifact = get_object_or_404(SamplingArtifact, pk=artifact_pk, run=run)
    try:
        return FileResponse(
            artifact.file.open("rb"),
            as_attachment=True,
            filename=artifact.original_name,
        )
    except FileNotFoundError:
        raise Http404("文件不存在。")


@login_required
@require_POST
def bundle_import(request):
    _require_authenticated(request)
    form = ResultBundleImportForm(request.POST, request.FILES, viewer=request)
    if not form.is_valid():
        messages.error(request, "结果包导入信息不完整。")
        return _index_page(request, bundle_form=form)
    project = form.cleaned_data["project"]
    try:
        run = import_result_bundle(
            project,
            form.cleaned_data["file"],
            request.user,
            name=form.cleaned_data.get("name") or "",
            version=form.cleaned_data.get("version") or "imported",
        )
        messages.success(request, "抽样结果包已导入，原抽样协议与运行指纹已保留。")
        return redirect("sampling:detail", pk=run.pk)
    except SamplingError as exc:
        form.add_error('file', str(exc))
        return _index_page(request, bundle_form=form)


@login_required
@require_POST
@transaction.atomic
def create_experiment(request, pk):
    run = get_object_or_404(_visible_runs(request).select_for_update().select_related('project'), pk=pk, archived_at__isnull=True)
    _require_manage(request, run)
    if not run.is_frozen:
        messages.error(request, "只有已冻结样本集才能建立实验。")
        return redirect("sampling:detail", pk=run.pk)

    existing = run.experiment_links.order_by("-created_at").first()
    if existing:
        messages.info(request, "该样本集已经建立过实验记录，已打开最近一条。")
        return redirect("experiment_edit", pk=existing.experiment_id)

    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    number = f"SMP-{run.pk}-{stamp}"
    experiment = Experiment.objects.create(
        number=number,
        title=f"{run.name} · 实验"[:160],
        purpose=(
            f"基于已冻结样本集“{run.name} {run.version}”开展实验。"
            f"\nSampling fingerprint: {run.run_fingerprint}"
        ),
        project=run.project,
        source_id=f"sampling:{run.pk}:{run.run_fingerprint}",
        batch=run.version,
        created_by=request.user,
    )
    SamplingExperimentLink.objects.create(run=run, experiment=experiment)
    messages.success(request, "已建立实验记录，请继续填写模型、Prompt、实验流程与结果。")
    return redirect("experiment_edit", pk=experiment.pk)


@login_required
@require_GET
def agent_config(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    if run.is_frozen:
        return JsonResponse({"ok": False, "error": "已冻结样本集不可重新采集。"}, status=409)
    return JsonResponse({"ok": True, "config": collection_config(run)})


@login_required
@require_POST
@transaction.atomic
def agent_import(request, pk):
    run = get_object_or_404(_visible_runs(request).select_for_update(), pk=pk, archived_at__isnull=True)
    _require_manage(request, run)
    if run.is_frozen:
        return JsonResponse({"ok": False, "error": "已冻结样本集不可导入候选论文。"}, status=409)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if payload.get("scope_signature") != collection_config(run)["scope_signature"]:
            return JsonResponse({"ok": False, "error": "研究范围已变更，请按新范围重新采集；旧任务不会写入新候选池。"}, status=409)
        records = payload.get("records", [])
        if not isinstance(records, list) or not records:
            raise SamplingError("本地采集器没有返回候选题录。")
        result = ingest_records(run, records, "CNKI Local Agent")
        return JsonResponse({"ok": True, **result})
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, SamplingError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
@require_GET
def agent_pdf_config(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    if not run.is_frozen:
        return JsonResponse({"ok": False, "error": "只有已冻结样本集才能下载正式样本 PDF。"}, status=409)
    records = [
        {"paper_id": p.paper_id, "title": p.title, "url": p.cnki_url, "run_id": run.pk}
        for p in run.candidates.filter(
            sample_role__in=[CandidatePaper.ROLE_MAIN, CandidatePaper.ROLE_HOLDOUT]
        ).order_by("paper_id")
    ]
    return JsonResponse({"ok": True, "records": records, "run_id": run.pk})


@login_required
@require_POST
def document_upload(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    from .documents import store_upload
    file = request.FILES.get('file')
    error = ''
    try:
        if not file:
            raise SamplingError('请选择 PDF 或含映射表的全文 ZIP。')
        docs, created = store_upload(run, file, (request.POST.get('paper_id') or '').strip(), request.user)
        if request.headers.get('Accept') != 'application/json':
            messages.success(request, f'已接收 {len(docs)} 份全文，新增 {created} 份；转换任务已进入队列。')
    except SamplingError as exc:
        error = str(exc)
        if request.headers.get('Accept') != 'application/json':
            messages.error(request, error)
    if request.headers.get('Accept') == 'application/json':
        if 'docs' not in locals():
            return JsonResponse({'ok': False, 'error': error or '全文上传失败，请检查 PDF 与样本编号'}, status=400)
        return JsonResponse({'ok': True, 'documents': [d.pk for d in docs], 'created': created})
    return redirect(reverse('sampling:detail', args=[pk]) + '#documents')


@login_required
@require_POST
def document_convert(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    from .documents import enqueue_documents
    if not run.is_frozen:
        messages.error(request, '请先冻结样本集。')
    else:
        count = enqueue_documents(run)
        messages.success(request, f'{count} 份 PDF 已加入转换队列。')
    return redirect(reverse('sampling:detail', args=[pk]) + '#documents')


@login_required
@require_GET
def document_status(request, pk):
    run = _run(request, pk)
    _require_authenticated(request)
    from .documents import latest_documents
    docs = latest_documents(run)
    return JsonResponse({key: sum(d.status == key for d in docs) for key in ('received','queued','running','ready','review','failed')})


@login_required
@require_GET
def document_download(request, pk, document_pk, kind):
    run = _run(request, pk)
    _require_authenticated(request)
    doc = get_object_or_404(SamplingDocument, pk=document_pk, candidate__run=run)
    if kind not in ('pdf', 'md'):
        raise Http404('文件类型不存在')
    file = doc.pdf_file if kind == 'pdf' else doc.md_file
    if not file:
        raise Http404('文件尚未生成')
    try:
        return FileResponse(file.open('rb'), as_attachment=True,
                            filename=doc.original_name if kind == 'pdf' else f'{doc.candidate.paper_id}.md')
    except FileNotFoundError:
        raise Http404('文件不存在')


@login_required
@require_GET
def document_bundle_download(request, pk):
    run = _run(request, pk)
    _require_authenticated(request)
    from .documents import document_bundle
    from django.http import HttpResponse
    response = HttpResponse(document_bundle(run), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="sampling_{run.pk}_canonical_md.zip"'
    return response


@login_required
@require_GET
def pdf_manifest_template(request, pk):
    run = _run(request, pk)
    _require_authenticated(request)
    from django.http import HttpResponse
    from .services import _csv_bytes
    data = _csv_bytes(['paper_id','source_pdf'], [{'paper_id': p.paper_id, 'source_pdf': ''} for p in run.candidates.exclude(paper_id='').order_by('paper_id')])
    response = HttpResponse(data, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="pdf_manifest.csv"'
    return response


@login_required
@require_POST
def agent_pdf_report(request, pk):
    run = _run(request, pk)
    _require_manage(request, run)
    if not run.is_frozen:
        return JsonResponse({'error': '请先冻结抽样'}, status=409)
    try:
        rows = json.loads(request.body).get('records')
        if not isinstance(rows, list) or len(rows) > 1000:
            raise SamplingError('PDF 报告格式不正确')
        count = 0
        for row in rows:
            if not isinstance(row, dict):
                raise SamplingError('PDF 报告条目不正确')
            paper = run.candidates.filter(paper_id=row.get('paper_id')).exclude(paper_id='').first()
            if paper and not paper.documents.exists():
                # 只有文件回传才是已接收；下载报告不能冒充文件已经进入工作台。
                status = '本机已下载，等待上传' if str(row.get('status','')).startswith('downloaded') else '需人工下载'
                CandidatePaper.objects.filter(pk=paper.pk).update(pdf_status=status)
                count += 1
        return JsonResponse({'ok': True, 'updated': count})
    except (ValueError, AttributeError, SamplingError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
