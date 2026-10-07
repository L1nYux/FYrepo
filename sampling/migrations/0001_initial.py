# Generated for Sampling formal module v1
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import sampling.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0011_emailverificationcode"),
    ]

    operations = [
        migrations.CreateModel(
            name="SamplingRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, verbose_name="样本集名称")),
                ("version", models.CharField(default="v1", max_length=40, verbose_name="版本")),
                ("periods", models.JSONField(default=list, verbose_name="研究时期")),
                ("selected_tiers", models.JSONField(default=list, verbose_name="期刊层级")),
                ("selected_journals", models.JSONField(default=list, verbose_name="期刊范围")),
                ("main_n", models.PositiveSmallIntegerField(default=1, help_text="对每个“期刊 × 时期”抽样格抽取的主样本数。", verbose_name="每个主抽样格样本数")),
                ("reserve_n", models.PositiveSmallIntegerField(default=1, help_text="每个抽样格预先冻结的备用样本数。", verbose_name="每个抽样格备用数")),
                ("holdout_enabled", models.BooleanField(default=False, verbose_name="启用留出样本")),
                ("holdout_start", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="留出期开始年份")),
                ("holdout_end", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="留出期结束年份")),
                ("holdout_n", models.PositiveSmallIntegerField(default=1, verbose_name="每个留出抽样格样本数")),
                ("sampling_method", models.CharField(choices=[("hash_issue_balanced", "确定性哈希 + 期号均衡"), ("hash_simple", "确定性哈希直接排序")], default="hash_issue_balanced", max_length=40, verbose_name="抽样方法")),
                ("sampling_seed", models.CharField(default="law_sampling_v1", max_length=160, verbose_name="抽样种子")),
                ("status", models.CharField(choices=[("draft", "草稿"), ("review", "待复核"), ("ready", "可冻结"), ("frozen", "已冻结"), ("archived", "已归档")], default="draft", max_length=20, verbose_name="状态")),
                ("protocol_version", models.CharField(default="sampling_protocol_v1", max_length=40)),
                ("sampling_frame_sha256", models.CharField(blank=True, max_length=64)),
                ("candidate_registry_sha256", models.CharField(blank=True, max_length=64)),
                ("run_fingerprint", models.CharField(blank=True, max_length=64, verbose_name="运行指纹")),
                ("protocol", models.JSONField(blank=True, default=dict, verbose_name="抽样协议")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("frozen_at", models.DateTimeField(blank=True, null=True, verbose_name="冻结时间")),
                ("archived_at", models.DateTimeField(blank=True, null=True, verbose_name="归档时间")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sampling_runs", to=settings.AUTH_USER_MODEL, verbose_name="创建人")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sampling_runs", to="core.project", verbose_name="所属项目")),
            ],
            options={"verbose_name": "样本集", "verbose_name_plural": "样本集", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CandidatePaper",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("candidate_key", models.CharField(max_length=500, verbose_name="候选论文稳定键")),
                ("title", models.CharField(max_length=1000, verbose_name="题名")),
                ("authors", models.TextField(blank=True, verbose_name="作者")),
                ("journal", models.CharField(max_length=300, verbose_name="期刊")),
                ("year", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="年份")),
                ("issue", models.CharField(blank=True, max_length=80, verbose_name="期号")),
                ("volume", models.CharField(blank=True, max_length=80, verbose_name="卷")),
                ("doi", models.CharField(blank=True, max_length=300, verbose_name="DOI")),
                ("cnki_url", models.URLField(blank=True, max_length=1000, verbose_name="知网链接")),
                ("cnki_dbcode", models.CharField(blank=True, max_length=80)),
                ("cnki_filename", models.CharField(blank=True, max_length=300)),
                ("keywords", models.TextField(blank=True, verbose_name="关键词")),
                ("abstract", models.TextField(blank=True, verbose_name="摘要")),
                ("clc", models.CharField(blank=True, max_length=200, verbose_name="中图分类号")),
                ("article_type", models.CharField(blank=True, max_length=200, verbose_name="文献类型")),
                ("stratum_id", models.CharField(blank=True, max_length=80, verbose_name="抽样格编号")),
                ("period", models.CharField(blank=True, max_length=40, verbose_name="时期")),
                ("tier", models.CharField(blank=True, max_length=20, verbose_name="层级")),
                ("journal_family_name", models.CharField(blank=True, max_length=300, verbose_name="期刊规范名")),
                ("frame_match_status", models.CharField(blank=True, max_length=40)),
                ("eligibility_status", models.CharField(choices=[("ELIGIBLE_AUTO", "自动判定可纳入"), ("EXCLUDED_AUTO", "自动判定排除"), ("UNCERTAIN", "待人工复核"), ("HOLD_METADATA", "元数据异常")], default="UNCERTAIN", max_length=40, verbose_name="入选状态")),
                ("eligibility_reason", models.CharField(blank=True, max_length=500, verbose_name="判定原因")),
                ("decision", models.CharField(blank=True, choices=[("", "待处理"), ("include", "选入"), ("exclude", "排除")], default="", max_length=20, verbose_name="人工决策")),
                ("sample_role", models.CharField(blank=True, choices=[("MAIN", "主样本"), ("HOLDOUT", "留出样本"), ("RESERVE", "备用样本")], default="", max_length=20, verbose_name="样本角色")),
                ("paper_id", models.CharField(blank=True, max_length=40, verbose_name="样本编号")),
                ("draw_hash", models.CharField(blank=True, max_length=64, verbose_name="抽样哈希")),
                ("draw_rank", models.PositiveIntegerField(blank=True, null=True, verbose_name="抽样顺位")),
                ("issue_group", models.CharField(blank=True, max_length=160)),
                ("stratum_pool_size", models.PositiveIntegerField(blank=True, null=True)),
                ("reserve_rank", models.PositiveIntegerField(blank=True, null=True)),
                ("reserve_for_role", models.CharField(blank=True, max_length=20)),
                ("pdf_status", models.CharField(default="待处理", max_length=80, verbose_name="PDF状态")),
                ("md_status", models.CharField(default="待处理", max_length=80, verbose_name="Markdown状态")),
                ("source_file", models.CharField(blank=True, max_length=300, verbose_name="来源文件")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="candidates", to="sampling.samplingrun", verbose_name="样本集")),
            ],
            options={"ordering": ["journal", "year", "issue", "title"]},
        ),
        migrations.CreateModel(
            name="SamplingArtifact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("artifact_type", models.CharField(choices=[("frame", "抽样框"), ("registry", "候选池"), ("protocol", "抽样协议"), ("certificate", "逐样本抽样凭证"), ("ranking", "候选池完整排序"), ("selected", "已抽选样本"), ("reserve", "备用样本"), ("issues", "抽样问题"), ("download_queue", "PDF下载任务"), ("evidence_queue", "证据补全任务"), ("bundle", "完整结果包")], max_length=40)),
                ("original_name", models.CharField(max_length=300)),
                ("file", models.FileField(upload_to=sampling.models.artifact_upload_to)),
                ("sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="artifacts", to="sampling.samplingrun", verbose_name="样本集")),
            ],
            options={"ordering": ["artifact_type", "-created_at"]},
        ),
        migrations.CreateModel(
            name="SamplingExperimentLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("experiment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sampling_link", to="core.experiment")),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="experiment_links", to="sampling.samplingrun")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="candidatepaper",
            constraint=models.UniqueConstraint(fields=("run", "candidate_key"), name="sampling_unique_candidate_per_run"),
        ),
        migrations.AddConstraint(
            model_name="candidatepaper",
            constraint=models.UniqueConstraint(condition=~models.Q(paper_id=""), fields=("run", "paper_id"), name="sampling_unique_paper_id_per_run"),
        ),
    ]
