"""项目树、留言、统一附件、报销与最终成果。

这次升级把“任务列表”改成“项目 → 母任务 → 子任务”，并新增留言、报销申请和统一附件表，
同时移除操作日志。既有数据不会被丢弃：升级前已存在的任务会整体归入一个升级项目，
旧的成果文件与财务凭证会转成统一附件记录。

生成方式：按模型差异手工编写（因为要给既有任务补上所属项目）。改动模型后请用
`manage.py makemigrations --check --dry-run` 确认没有遗漏。
"""

import core.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def move_legacy_data(apps, schema_editor):
    """把升级前的任务、成果文件与财务凭证搬到新结构里。"""
    Project = apps.get_model('core', 'Project')
    Task = apps.get_model('core', 'Task')
    Submission = apps.get_model('core', 'Submission')
    FinanceEntry = apps.get_model('core', 'FinanceEntry')
    Attachment = apps.get_model('core', 'Attachment')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    if Task.objects.exists():
        owner = (User.objects.filter(is_superuser=True, is_active=True).order_by('pk').first()
                 or User.objects.filter(is_active=True).order_by('pk').first())
        project = Project.objects.create(
            name='升级前的既有任务',
            goal='工作台升级前已存在的任务，已整体归入本项目；请按实际研究方向重新归类并指定负责人。',
            owner=owner,
            created_by=owner,
            status='active',
        )
        Task.objects.update(project=project)

    for submission in Submission.objects.exclude(attachment='').iterator():
        if submission.attachment:
            Attachment.objects.create(
                submission=submission,
                file=submission.attachment,
                original_name=(submission.original_name or 'attachment')[:255],
                uploaded_by=submission.author,
            )

    for entry in FinanceEntry.objects.exclude(receipt='').iterator():
        if entry.receipt:
            Attachment.objects.create(
                entry=entry,
                file=entry.receipt,
                original_name=(entry.receipt_name or 'receipt')[:255],
                uploaded_by=entry.created_by,
            )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160, verbose_name='项目名称')),
                ('goal', models.TextField(max_length=3000, verbose_name='项目目标')),
                ('description', models.TextField(blank=True, max_length=5000, verbose_name='项目说明')),
                ('status', models.CharField(choices=[('active', '进行中'), ('paused', '已暂停'), ('closed', '已结项')], default='active', max_length=12, verbose_name='状态')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('closed_at', models.DateTimeField(blank=True, null=True, verbose_name='结项时间')),
                ('archived_at', models.DateTimeField(blank=True, null=True, verbose_name='归档时间')),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='closed_projects', to=settings.AUTH_USER_MODEL, verbose_name='结项人')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_projects', to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
                ('members', models.ManyToManyField(blank=True, related_name='projects', to=settings.AUTH_USER_MODEL, verbose_name='项目成员')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='owned_projects', to=settings.AUTH_USER_MODEL, verbose_name='项目负责人')),
            ],
            options={
                'verbose_name': '项目',
                'verbose_name_plural': '项目',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='task',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='tasks', to='core.project', verbose_name='所属项目'),
        ),
        migrations.AddField(
            model_name='task',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='core.task', verbose_name='母任务'),
        ),
        migrations.AddField(
            model_name='task',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='结项时间'),
        ),
        migrations.AddField(
            model_name='task',
            name='closed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='closed_tasks', to=settings.AUTH_USER_MODEL, verbose_name='结项人'),
        ),
        migrations.AlterField(
            model_name='task',
            name='description',
            field=models.TextField(max_length=5000, verbose_name='任务说明'),
        ),
        migrations.AlterField(
            model_name='task',
            name='assignee',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='assigned_tasks', to=settings.AUTH_USER_MODEL, verbose_name='任务负责人'),
        ),
        migrations.AlterModelOptions(
            name='task',
            options={'ordering': ['due_date', 'created_at'], 'verbose_name': '任务', 'verbose_name_plural': '任务'},
        ),
        migrations.RenameField(
            model_name='submission',
            old_name='note',
            new_name='summary',
        ),
        migrations.AlterField(
            model_name='submission',
            name='summary',
            field=models.TextField(max_length=5000, verbose_name='成果内容'),
        ),
        migrations.AlterField(
            model_name='submission',
            name='author',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='submissions', to=settings.AUTH_USER_MODEL, verbose_name='提交者'),
        ),
        migrations.AlterField(
            model_name='submission',
            name='review_note',
            field=models.TextField(blank=True, max_length=3000, verbose_name='审核结论'),
        ),
        migrations.AddField(
            model_name='submission',
            name='is_final',
            field=models.BooleanField(default=False, verbose_name='选为最终成果'),
        ),
        migrations.AddField(
            model_name='submission',
            name='final_note',
            field=models.TextField(blank=True, default='', max_length=1000, verbose_name='选用说明'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='submission',
            name='final_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='finalized_submissions', to=settings.AUTH_USER_MODEL, verbose_name='选用人'),
        ),
        migrations.AddField(
            model_name='submission',
            name='final_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='选用时间'),
        ),
        migrations.AlterField(
            model_name='financeentry',
            name='kind',
            field=models.CharField(choices=[('income', '收入'), ('expense', '支出'), ('bonus', '奖金'), ('api', 'API 成本'), ('reimburse', '报销入账')], max_length=10, verbose_name='类型'),
        ),
        migrations.AlterField(
            model_name='financeentry',
            name='created_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='finance_entries', to=settings.AUTH_USER_MODEL, verbose_name='记账人'),
        ),
        migrations.AddField(
            model_name='financeentry',
            name='voided_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='voided_entries', to=settings.AUTH_USER_MODEL, verbose_name='作废人'),
        ),
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('goal', '目标'), ('idea', '思路'), ('issue', '问题'), ('conclusion', '结论'), ('note', '讨论')], default='note', max_length=12, verbose_name='类型')),
                ('body', models.TextField(max_length=4000, verbose_name='内容')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='留言时间')),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='comments', to=settings.AUTH_USER_MODEL, verbose_name='留言人')),
                ('submission', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='core.submission', verbose_name='针对成果')),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='core.task', verbose_name='任务')),
            ],
            options={
                'verbose_name': '任务留言',
                'verbose_name_plural': '任务留言',
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='ExpenseClaim',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='申请金额（元）')),
                ('occurred_on', models.DateField(verbose_name='发生日期')),
                ('memo', models.TextField(max_length=3000, verbose_name='事由')),
                ('status', models.CharField(choices=[('pending', '待审核'), ('approved', '已通过并入账'), ('rejected', '已驳回')], default='pending', max_length=12, verbose_name='状态')),
                ('review_note', models.TextField(blank=True, max_length=3000, verbose_name='审核结论')),
                ('reviewed_at', models.DateTimeField(blank=True, null=True, verbose_name='审核时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='提交时间')),
                ('applicant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='claims', to=settings.AUTH_USER_MODEL, verbose_name='申请人')),
                ('entry', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='claim', to='core.financeentry', verbose_name='入账记录')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_claims', to=settings.AUTH_USER_MODEL, verbose_name='审核人')),
            ],
            options={
                'verbose_name': '报销申请',
                'verbose_name_plural': '报销申请',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Attachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to=core.models.private_path, validators=[core.models.validate_private_file], verbose_name='文件')),
                ('original_name', models.CharField(max_length=255, verbose_name='原文件名')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='上传时间')),
                ('claim', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='core.expenseclaim', verbose_name='报销申请')),
                ('comment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='core.comment', verbose_name='留言')),
                ('entry', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='core.financeentry', verbose_name='财务记录')),
                ('submission', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='core.submission', verbose_name='成果')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='uploaded_attachments', to=settings.AUTH_USER_MODEL, verbose_name='上传人')),
            ],
            options={
                'verbose_name': '附件',
                'verbose_name_plural': '附件',
                'ordering': ['created_at'],
            },
        ),
        migrations.RunPython(move_legacy_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name='submission', name='attachment'),
        migrations.RemoveField(model_name='submission', name='original_name'),
        migrations.RemoveField(model_name='financeentry', name='receipt'),
        migrations.RemoveField(model_name='financeentry', name='receipt_name'),
        migrations.AlterField(
            model_name='task',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tasks', to='core.project', verbose_name='所属项目'),
        ),
        migrations.DeleteModel(name='AuditEvent'),
    ]
