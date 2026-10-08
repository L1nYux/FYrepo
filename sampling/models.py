from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from core.tenancy import required_workspace_id


def artifact_upload_to(instance, filename):
    return f"sampling/{instance.run_id}/{instance.artifact_type}/{filename}"


class SamplingRun(models.Model):
    workspace = models.ForeignKey('core.Workspace', on_delete=models.PROTECT,
        default=required_workspace_id, editable=False, verbose_name='归属')
    DRAFT = "draft"
    REVIEW = "review"
    READY = "ready"
    FROZEN = "frozen"
    ARCHIVED = "archived"
    STATUS_CHOICES = [
        (DRAFT, "草稿"),
        (REVIEW, "待复核"),
        (READY, "可冻结"),
        (FROZEN, "已冻结"),
        (ARCHIVED, "已归档"),
    ]

    METHOD_HASH_ISSUE_BALANCED = "hash_issue_balanced"
    METHOD_HASH_SIMPLE = "hash_simple"
    METHOD_CHOICES = [
        (METHOD_HASH_ISSUE_BALANCED, "确定性哈希 + 期号均衡"),
        (METHOD_HASH_SIMPLE, "确定性哈希直接排序"),
    ]

    project = models.ForeignKey(
        "core.Project",
        on_delete=models.PROTECT,
        related_name="sampling_runs",
        verbose_name="关联项目", null=True, blank=True,
    )
    name = models.CharField("样本集名称", max_length=160)
    version = models.CharField("版本", max_length=40, default="v1")
    source_run = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="versions", verbose_name="来源版本")

    periods = models.JSONField("研究时期", default=list)
    selected_tiers = models.JSONField("期刊层级", default=list)
    selected_journals = models.JSONField("期刊范围", default=list)

    main_n = models.PositiveSmallIntegerField(
        "每个主抽样格样本数", default=1,
        help_text="对每个“期刊 × 时期”抽样格抽取的主样本数。"
    )
    reserve_n = models.PositiveSmallIntegerField(
        "每个抽样格备用数", default=1,
        help_text="每个抽样格预先冻结的备用样本数。"
    )
    holdout_enabled = models.BooleanField("启用留出样本", default=False)
    holdout_start = models.PositiveSmallIntegerField("留出期开始年份", null=True, blank=True)
    holdout_end = models.PositiveSmallIntegerField("留出期结束年份", null=True, blank=True)
    holdout_n = models.PositiveSmallIntegerField("每个留出抽样格样本数", default=1)

    sampling_method = models.CharField(
        "抽样方法", max_length=40, choices=METHOD_CHOICES,
        default=METHOD_HASH_ISSUE_BALANCED
    )
    sampling_seed = models.CharField("抽样种子", max_length=160, default="law_sampling_v1")

    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    protocol_version = models.CharField(max_length=40, default="sampling_protocol_v1")
    sampling_frame_sha256 = models.CharField(max_length=64, blank=True)
    candidate_registry_sha256 = models.CharField(max_length=64, blank=True)
    run_fingerprint = models.CharField("运行指纹", max_length=64, blank=True)
    protocol = models.JSONField("抽样协议", default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sampling_runs",
        verbose_name="创建人",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    frozen_at = models.DateTimeField("冻结时间", null=True, blank=True)
    archived_at = models.DateTimeField("归档时间", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "样本集"
        verbose_name_plural = "样本集"

    def __str__(self):
        return f"{self.name} · {self.version}"

    @property
    def is_frozen(self):
        return self.status == self.FROZEN or self.frozen_at is not None

    @property
    def project_label(self):
        return self.project.name if self.project_id else "独立样本集"

    def clean(self):
        from .scope import validate_scope
        errors = validate_scope(self)
        if self.project_id and self.project.workspace_id != self.workspace_id:
            errors['project'] = '关联项目必须与样本集属于同一归属。'
        if self.source_run_id and self.source_run.workspace_id != self.workspace_id:
            errors['source_run'] = '来源版本必须与样本集属于同一归属。'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old and old.workspace_id != self.workspace_id:
                raise ValidationError('不能改变样本集归属。')
            if old and old.is_frozen:
                immutable = [
                    "project_id", "name", "version", "periods", "selected_tiers",
                    "selected_journals", "main_n", "reserve_n", "holdout_enabled",
                    "holdout_start", "holdout_end", "holdout_n",
                    "sampling_method", "sampling_seed",
                    "source_run_id", "created_by_id", "protocol_version", "protocol",
                    "sampling_frame_sha256", "candidate_registry_sha256", "run_fingerprint", "frozen_at",
                ]
                changed = [f for f in immutable if getattr(old, f) != getattr(self, f)]
                if changed:
                    raise ValidationError(
                        "已冻结样本集不可修改研究范围或抽样参数；请创建新版本。"
                    )
        self.full_clean()
        return super().save(*args, **kwargs)


class CandidatePaper(models.Model):
    ELIGIBLE_AUTO = "ELIGIBLE_AUTO"
    EXCLUDED_AUTO = "EXCLUDED_AUTO"
    UNCERTAIN = "UNCERTAIN"
    HOLD_METADATA = "HOLD_METADATA"
    ELIGIBILITY_CHOICES = [
        (ELIGIBLE_AUTO, "自动判定可纳入"),
        (EXCLUDED_AUTO, "自动判定排除"),
        (UNCERTAIN, "待人工复核"),
        (HOLD_METADATA, "元数据异常"),
    ]

    PENDING = ""
    INCLUDE = "include"
    EXCLUDE = "exclude"
    DECISION_CHOICES = [
        (PENDING, "待处理"),
        (INCLUDE, "选入"),
        (EXCLUDE, "排除"),
    ]

    ROLE_MAIN = "MAIN"
    ROLE_HOLDOUT = "HOLDOUT"
    ROLE_RESERVE = "RESERVE"
    ROLE_CHOICES = [
        (ROLE_MAIN, "主样本"),
        (ROLE_HOLDOUT, "留出样本"),
        (ROLE_RESERVE, "备用样本"),
    ]

    run = models.ForeignKey(
        SamplingRun, on_delete=models.CASCADE, related_name="candidates", verbose_name="样本集"
    )
    candidate_key = models.CharField("候选论文稳定键", max_length=500)
    title = models.CharField("题名", max_length=1000)
    authors = models.TextField("作者", blank=True)
    journal = models.CharField("期刊", max_length=300)
    year = models.PositiveSmallIntegerField("年份", null=True, blank=True)
    issue = models.CharField("期号", max_length=80, blank=True)
    volume = models.CharField("卷", max_length=80, blank=True)
    doi = models.CharField("DOI", max_length=300, blank=True)
    cnki_url = models.URLField("知网链接", max_length=1000, blank=True)
    cnki_dbcode = models.CharField(max_length=80, blank=True)
    cnki_filename = models.CharField(max_length=300, blank=True)
    keywords = models.TextField("关键词", blank=True)
    abstract = models.TextField("摘要", blank=True)
    clc = models.CharField("中图分类号", max_length=200, blank=True)
    article_type = models.CharField("文献类型", max_length=200, blank=True)

    stratum_id = models.CharField("抽样格编号", max_length=80, blank=True)
    period = models.CharField("时期", max_length=40, blank=True)
    tier = models.CharField("层级", max_length=20, blank=True)
    journal_family_name = models.CharField("期刊规范名", max_length=300, blank=True)
    frame_match_status = models.CharField(max_length=40, blank=True)
    cross_disciplinary_journal = models.BooleanField(default=False)

    eligibility_status = models.CharField(
        "入选状态", max_length=40, choices=ELIGIBILITY_CHOICES, default=UNCERTAIN
    )
    eligibility_reason = models.CharField("判定原因", max_length=500, blank=True)
    decision = models.CharField(
        "人工决策", max_length=20, choices=DECISION_CHOICES, blank=True, default=""
    )

    sample_role = models.CharField(
        "样本角色", max_length=20, choices=ROLE_CHOICES, blank=True, default=""
    )
    paper_id = models.CharField("样本编号", max_length=40, blank=True)
    draw_hash = models.CharField("抽样哈希", max_length=64, blank=True)
    draw_rank = models.PositiveIntegerField("抽样顺位", null=True, blank=True)
    issue_group = models.CharField(max_length=160, blank=True)
    stratum_pool_size = models.PositiveIntegerField(null=True, blank=True)
    reserve_rank = models.PositiveIntegerField(null=True, blank=True)
    reserve_for_role = models.CharField(max_length=20, blank=True)

    pdf_status = models.CharField("PDF状态", max_length=80, default="待处理")
    md_status = models.CharField("Markdown状态", max_length=80, default="待处理")

    source_file = models.CharField("来源文件", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["journal", "year", "issue", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "candidate_key"], name="sampling_unique_candidate_per_run"
            ),
            models.UniqueConstraint(
                fields=["run", "paper_id"],
                condition=~Q(paper_id=""),
                name="sampling_unique_paper_id_per_run",
            ),
        ]

    def __str__(self):
        return self.paper_id or self.title


class SamplingArtifact(models.Model):
    TYPE_FRAME = "frame"
    TYPE_REGISTRY = "registry"
    TYPE_PROTOCOL = "protocol"
    TYPE_CERTIFICATE = "certificate"
    TYPE_RANKING = "ranking"
    TYPE_SELECTED = "selected"
    TYPE_RESERVE = "reserve"
    TYPE_ISSUES = "issues"
    TYPE_DOWNLOAD_QUEUE = "download_queue"
    TYPE_EVIDENCE_QUEUE = "evidence_queue"
    TYPE_BUNDLE = "bundle"
    TYPE_PROTOCOL_MD = "protocol_md"
    TYPE_SAFE_MANIFEST = "safe_manifest"
    TYPE_LABELS = "labels_seed"
    TYPE_CHOICES = [
        (TYPE_FRAME, "抽样框"),
        (TYPE_REGISTRY, "候选池"),
        (TYPE_PROTOCOL, "抽样协议"),
        (TYPE_CERTIFICATE, "逐样本抽样凭证"),
        (TYPE_RANKING, "候选池完整排序"),
        (TYPE_SELECTED, "已抽选样本"),
        (TYPE_RESERVE, "备用样本"),
        (TYPE_ISSUES, "抽样问题"),
        (TYPE_DOWNLOAD_QUEUE, "PDF下载任务"),
        (TYPE_EVIDENCE_QUEUE, "证据补全任务"),
        (TYPE_BUNDLE, "完整结果包"),
        (TYPE_PROTOCOL_MD, "抽样协议说明"),
        (TYPE_SAFE_MANIFEST, "样本编号清单"),
        (TYPE_LABELS, "真实标签种子表"),
    ]

    run = models.ForeignKey(
        SamplingRun, on_delete=models.CASCADE, related_name="artifacts", verbose_name="样本集"
    )
    artifact_type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    original_name = models.CharField(max_length=300)
    file = models.FileField(upload_to=artifact_upload_to)
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["artifact_type", "-created_at"]

    def __str__(self):
        return f"{self.run} · {self.get_artifact_type_display()}"


class SamplingExperimentLink(models.Model):
    run = models.ForeignKey(
        SamplingRun, on_delete=models.PROTECT, related_name="experiment_links"
    )
    experiment = models.OneToOneField(
        "core.Experiment", on_delete=models.CASCADE, related_name="sampling_link"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def document_upload_to(instance, filename):
    import uuid
    return f"sampling/{instance.candidate.run_id}/documents/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class SamplingDocument(models.Model):
    """原始 PDF 的版本与异步转换记录；不覆盖冻结题录或已有全文版本。"""
    RECEIVED, QUEUED, RUNNING, READY, REVIEW, FAILED = (
        "received", "queued", "running", "ready", "review", "failed")
    STATUS_CHOICES = [(RECEIVED, "PDF 已接收"), (QUEUED, "等待转换"), (RUNNING, "正在转换"),
                      (READY, "转换完成"), (REVIEW, "需人工检查"), (FAILED, "转换失败")]
    candidate = models.ForeignKey(CandidatePaper, on_delete=models.PROTECT, related_name="documents")
    original_name = models.CharField("原 PDF 文件名", max_length=255)
    pdf_file = models.FileField(upload_to=document_upload_to)
    pdf_sha256 = models.CharField(max_length=64)
    md_file = models.FileField(upload_to=document_upload_to, blank=True)
    md_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=RECEIVED)
    pages = models.PositiveIntegerField(default=0)
    characters = models.PositiveIntegerField(default=0)
    warnings = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    converter_version = models.CharField(max_length=80, blank=True)
    claim_token = models.CharField(max_length=40, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["status", "created_at"], name="sampling_document_queue")]
        constraints = [models.UniqueConstraint(fields=["candidate", "pdf_sha256"], name="sampling_unique_pdf")]
