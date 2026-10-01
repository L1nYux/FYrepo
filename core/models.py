"""科研团队工作台的数据模型。

结构：项目 → 母任务 → 子任务（母任务下可再分子任务，构成不同的探索分支）。
成果允许纯文本，附件可选；各层任务都有留言（目标／思路／问题／结论）。
财务为团队账本，成员可提交报销申请，管理员审核后入账。
聊天室分「开发者聊天室」（管理员与开发者）和「公共聊天室」（所有登录用户）。

记录保持精简：不保存网站运行流水，也不保存用户操作审计。
"""

import hashlib
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

# 附件允许的类型：文本、PDF、Word、Excel、Markdown 与常见图片。
ALLOWED_EXTENSIONS = {
    '.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.md', '.markdown', '.py', '.ipynb', '.js', '.ts', '.r', '.sh', '.sql', '.json', '.yaml', '.yml', '.toml', '.csv', '.zip',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
}
EXTENSION_HINT = 'TXT、PDF、Word、Excel、Markdown 或图片'
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 5
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

# 财务口径：这些类型的金额属于流出，用于直接求余额。
OUTFLOW_KINDS = {'expense', 'bonus', 'api', 'reimburse'}


def validate_private_file(value):
    """单个私有附件的类型与大小校验。"""
    if Path(value.name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError(f'只允许 {EXTENSION_HINT} 文件。')
    if value.size > MAX_FILE_BYTES:
        raise ValidationError('单个文件不能超过 20 MB。')


def validate_private_files(files):
    """一次上传的多个附件：逐个校验并限制数量与总大小。"""
    files = [item for item in files if item]
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise ValidationError(f'一次最多上传 {MAX_FILES_PER_UPLOAD} 个文件。')
    total = 0
    for item in files:
        validate_private_file(item)
        total += item.size
    if total > MAX_UPLOAD_BYTES:
        raise ValidationError('本次上传的文件总大小不能超过 40 MB。')
    return files


def private_path(instance, filename):
    """私有附件落盘路径：不使用原始文件名，也不提供公开 URL。"""
    return f'{instance._meta.model_name}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class MemberProfile(models.Model):
    """账号层级档案：区分「开发者」和「普通用户」。

    管理员由 User.is_staff 表示，不必写在这里。没有档案的账号一律按开发者处理，
    这样升级前的既有账号（邀请码注册的开发者、createsuperuser 建的管理员）行为不变。
    普通用户凭「注册普通用户」入口自助创建，只能看到项目展示、公共聊天室和关于页面。
    """

    DEVELOPER, NORMAL = 'developer', 'normal'
    TIERS = [(DEVELOPER, '开发者'), (NORMAL, '普通用户')]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='member_profile', verbose_name='账号')
    tier = models.CharField('账号层级', max_length=12, choices=TIERS, default=DEVELOPER)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '账号档案'
        verbose_name_plural = '账号档案'

    def __str__(self):
        return f'{self.user} · {self.get_tier_display()}'


class Invite(models.Model):
    """一次性开发者邀请码。只保存摘要，明文仅在创建时显示一次。"""

    code_hash = models.CharField('邀请码摘要', max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_invites', verbose_name='创建者')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    expires_at = models.DateTimeField('过期时间')
    used_by = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='used_invite', verbose_name='使用者')
    used_at = models.DateTimeField('使用时间', null=True, blank=True)
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '邀请码'
        verbose_name_plural = '邀请码'

    @classmethod
    def issue(cls, admin, days=7):
        from datetime import timedelta
        code = secrets.token_urlsafe(24)
        invite = cls.objects.create(code_hash=hashlib.sha256(code.encode()).hexdigest(), created_by=admin,
                                    expires_at=timezone.now() + timedelta(days=days))
        return invite, code

    @property
    def state(self):
        if self.used_at:
            return '已使用'
        if self.revoked_at:
            return '已撤销'
        if self.expires_at <= timezone.now():
            return '已过期'
        return '可使用'


def summarise_progress(rows):
    """汇总项目进度：母任务取子任务的平均值，项目取各母任务的平均值。

    rows 为 (project_id, task_id, parent_id, progress) 的可迭代对象，
    一次遍历即可算出全部项目，避免逐个项目查询。
    """
    board = {}
    for project_id, task_id, parent_id, progress in rows:
        entry = board.setdefault(project_id, {'mothers': {}, 'children': {}})
        if parent_id is None:
            entry['mothers'][task_id] = progress
        else:
            entry['children'].setdefault(parent_id, []).append(progress)
    result = {}
    for project_id, entry in board.items():
        values = []
        for task_id, own in entry['mothers'].items():
            kids = entry['children'].get(task_id)
            values.append(round(sum(kids) / len(kids)) if kids else own)
        result[project_id] = round(sum(values) / len(values)) if values else 0
    return result


class Project(models.Model):
    """由管理员创建的项目：确定目标，指定项目负责人和成员。"""

    ACTIVE, PAUSED, CLOSED = 'active', 'paused', 'closed'
    STATUS = [(ACTIVE, '进行中'), (PAUSED, '已暂停'), (CLOSED, '已结项')]

    public_state = models.CharField('公开状态', max_length=10, choices=[('internal','内部'),('pending','待公开审核'),('public','已公开')], default='internal')
    public_summary = models.TextField('公开简介', max_length=2000, blank=True)
    name = models.CharField('项目名称', max_length=160)
    goal = models.TextField('项目目标', max_length=3000)
    description = models.TextField('项目说明', max_length=5000, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='owned_projects', verbose_name='项目负责人')
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='projects', verbose_name='项目成员')
    status = models.CharField('状态', max_length=12, choices=STATUS, default=ACTIVE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_projects', verbose_name='创建者')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    closed_at = models.DateTimeField('结项时间', null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='closed_projects', verbose_name='结项人')
    archived_at = models.DateTimeField('归档时间', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '项目'
        verbose_name_plural = '项目'

    def __str__(self):
        return self.name

    @property
    def progress(self):
        """项目进度取各母任务进度（母任务进度由其子任务汇总）的平均值。"""
        rows = self.tasks.filter(archived_at__isnull=True, parent__archived_at__isnull=True).values_list('project_id', 'id', 'parent_id', 'progress')
        return summarise_progress(rows).get(self.pk, 0)

    @property
    def participant_ids(self):
        return {self.owner_id} | set(self.members.values_list('pk', flat=True))

    def is_participant(self, user):
        return bool(user.is_authenticated and user.pk in self.participant_ids)


class Task(models.Model):
    """任务：parent 为空是母任务，否则是子任务（项目 → 母任务 → 子任务三级）。"""

    OPEN, SUBMITTED, COMPLETED = 'open', 'submitted', 'completed'
    STATUS = [(OPEN, '进行中'), (SUBMITTED, '待审核'), (COMPLETED, '已结项')]

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='tasks', verbose_name='所属项目')
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True,
                               related_name='children', verbose_name='母任务')
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='collaborative_tasks', verbose_name='协作成员')
    title = models.CharField('任务名称', max_length=160)
    description = models.TextField('任务说明', max_length=5000)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_tasks', verbose_name='任务负责人')
    due_date = models.DateField('截止日期', null=True, blank=True)
    progress = models.PositiveSmallIntegerField('进度（0-100）', default=0)
    status = models.CharField('状态', max_length=12, choices=STATUS, default=OPEN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_tasks', verbose_name='发布者')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    closed_at = models.DateTimeField('结项时间', null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='closed_tasks', verbose_name='结项人')
    archived_at = models.DateTimeField('归档时间', null=True, blank=True)

    class Meta:
        ordering = ['due_date', 'created_at']
        verbose_name = '任务'
        verbose_name_plural = '任务'

    def __str__(self):
        return self.title

    @property
    def is_mother(self):
        return self.parent_id is None

    @property
    def level_display(self):
        return '母任务' if self.is_mother else '子任务'

    @property
    def display_progress(self):
        """母任务进度由未归档子任务汇总，子任务使用自身进度。"""
        if not self.is_mother:
            return self.progress
        children = [child.progress for child in self.children.filter(archived_at__isnull=True)]
        if not children:
            return self.progress
        return round(sum(children) / len(children))

    def clean(self):
        if self.progress > 100:
            raise ValidationError({'progress': '进度不能超过 100。'})
        if self.parent_id:
            if self.parent.parent_id is not None:
                raise ValidationError({'parent': '只支持“项目 → 母任务 → 子任务”三级结构。'})
            if self.project_id and self.parent.project_id != self.project_id:
                raise ValidationError({'parent': '母任务必须属于同一个项目。'})
        if self.assignee_id and self.project_id and not self.project.is_participant(self.assignee):
            raise ValidationError({'assignee': '任务负责人须为项目负责人或项目成员。'})

    def save(self, *args, **kwargs):
        if self.parent_id and not self.project_id:
            self.project_id = self.parent.project_id
        super().save(*args, **kwargs)


class Submission(models.Model):
    """成果。正文为纯文本，附件可有可无、可有多个。

    成果可以挂在任务上，也可以直接挂在项目上（例如结题报告这类不属于单个任务的产出）。
    任何登录的开发者都可以发布成果；审核由管理员或项目负责人完成。
    """

    PENDING, ACCEPTED, REJECTED = 'pending', 'accepted', 'rejected'
    STATUS = [(PENDING, '待审核'), (ACCEPTED, '已通过'), (REJECTED, '已退回')]

    task = models.ForeignKey(Task, on_delete=models.PROTECT, null=True, blank=True,
                             related_name='submissions', verbose_name='任务')
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True, blank=True,
                                related_name='submissions', verbose_name='项目')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='submissions', verbose_name='提交者')
    summary = models.TextField('成果内容', max_length=5000, blank=True)
    source_url = models.URLField('源码或成果链接', blank=True)
    experiments = models.ManyToManyField('Experiment', blank=True, related_name='submissions', verbose_name='关联实验记录')
    status = models.CharField('审核状态', max_length=12, choices=STATUS, default=PENDING)
    review_note = models.TextField('审核结论', max_length=3000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='reviewed_submissions', verbose_name='审核人')
    reviewed_at = models.DateTimeField('审核时间', null=True, blank=True)
    is_final = models.BooleanField('选为最终成果', default=False)
    final_note = models.TextField('选用说明', max_length=1000, blank=True)
    final_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='finalized_submissions', verbose_name='选用人')
    final_at = models.DateTimeField('选用时间', null=True, blank=True)
    created_at = models.DateTimeField('提交时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '成果'
        verbose_name_plural = '成果'
        constraints = [
            models.CheckConstraint(
                condition=(Q(task__isnull=False, project__isnull=True)
                           | Q(task__isnull=True, project__isnull=False)),
                name='submission_has_one_target'),
        ]

    def clean(self):
        if (self.task_id is None) == (self.project_id is None):
            raise ValidationError('成果必须且只能属于一个任务或一个项目。')

    @property
    def owner_project(self):
        """成果所属项目：任务成果取任务所在的项目。"""
        return self.project if self.project_id else self.task.project

    @property
    def target_label(self):
        return f'任务：{self.task.title}' if self.task_id else f'项目：{self.project.name}'

    def __str__(self):
        return f'{self.target_label} · {self.author}'


class Comment(models.Model):
    """留言：任何开发者都可以对任务、项目或某一份成果留言。

    留言用来记录目标、思路、问题和结论，便于追溯上下文和明确责任。
    """

    GOAL, IDEA, ISSUE, CONCLUSION, NOTE = 'goal', 'idea', 'issue', 'conclusion', 'note'
    KINDS = [(GOAL, '目标'), (IDEA, '思路'), (ISSUE, '问题'), (CONCLUSION, '结论'), (NOTE, '讨论')]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='comments', verbose_name='任务')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True,
                                related_name='comments', verbose_name='项目')
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='comments', verbose_name='针对成果')
    kind = models.CharField('类型', max_length=12, choices=KINDS, default=NOTE)
    body = models.TextField('内容', max_length=4000)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='comments', verbose_name='留言人')
    created_at = models.DateTimeField('留言时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '留言'
        verbose_name_plural = '留言'
        constraints = [
            models.CheckConstraint(
                condition=(Q(task__isnull=False, project__isnull=True, submission__isnull=True)
                           | Q(task__isnull=True, project__isnull=False, submission__isnull=True)
                           | Q(task__isnull=True, project__isnull=True, submission__isnull=False)),
                name='comment_has_one_target'),
        ]

    def clean(self):
        if sum(1 for value in (self.task_id, self.project_id, self.submission_id) if value) != 1:
            raise ValidationError('留言必须且只能属于一个任务、一个项目或一份成果。')

    @property
    def context_label(self):
        """留言所在的位置，用于列表里显示来源。"""
        if self.task_id:
            return f'任务：{self.task.title}'
        if self.project_id:
            return f'项目：{self.project.name}'
        return self.submission.target_label


class ChatMessage(models.Model):
    """聊天室消息。两个房间共用一张表，靠 room 区分。

    - 开发者聊天室：所有管理员与开发者都能看、都能发言。
    - 公共聊天室：所有登录用户（含普通用户）都能看、都能发言。

    页面用轮询拉取新消息（按自增主键增量取），不引入 WebSocket，保持零新依赖。
    """

    PUBLIC, DEVELOPERS = 'public', 'developers'
    ROOMS = [(PUBLIC, '公共聊天室'), (DEVELOPERS, '开发者聊天室')]

    room = models.CharField('聊天室', max_length=12, choices=ROOMS, default=PUBLIC)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                               related_name='chat_messages', verbose_name='发言人')
    body = models.TextField('内容', max_length=2000)
    created_at = models.DateTimeField('发言时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '聊天室消息'
        verbose_name_plural = '聊天室消息'

    def __str__(self):
        return f'{self.get_room_display()} · {self.author}'

    @property
    def spoken_at(self):
        """发言时间，按站点时区显示到分钟。"""
        return timezone.localtime(self.created_at).strftime('%m-%d %H:%M')


class FinanceEntry(models.Model):
    """团队账本记录。所有开发者可见，只有管理员可以记账和作废。"""

    KIND = [('income', '收入'), ('expense', '支出'), ('bonus', '奖金'), ('api', 'API 成本'), ('reimburse', '报销入账')]

    kind = models.CharField('类型', max_length=10, choices=KIND)
    amount = models.DecimalField('金额（元）', max_digits=12, decimal_places=2)
    occurred_on = models.DateField('发生日期')
    memo = models.TextField('说明', max_length=3000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='finance_entries', verbose_name='记账人')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    voided_at = models.DateTimeField('作废时间', null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='voided_entries', verbose_name='作废人')

    class Meta:
        ordering = ['-occurred_on', '-created_at']
        verbose_name = '财务记录'
        verbose_name_plural = '财务记录'

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount}'

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': '金额必须大于 0。'})

    @property
    def signed_amount(self):
        """流出记负数，便于直接求余额。"""
        return -self.amount if self.kind in OUTFLOW_KINDS else self.amount


class ExpenseClaim(models.Model):
    """成员提交的报销申请及凭证，由管理员决定是否通过并入账。"""

    PENDING, APPROVED, REJECTED = 'pending', 'approved', 'rejected'
    STATUS = [(PENDING, '待审核'), (APPROVED, '已通过并入账'), (REJECTED, '已驳回')]

    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='claims', verbose_name='申请人')
    amount = models.DecimalField('申请金额（元）', max_digits=12, decimal_places=2)
    occurred_on = models.DateField('发生日期')
    memo = models.TextField('事由', max_length=3000)
    status = models.CharField('状态', max_length=12, choices=STATUS, default=PENDING)
    review_note = models.TextField('审核结论', max_length=3000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='reviewed_claims', verbose_name='审核人')
    reviewed_at = models.DateTimeField('审核时间', null=True, blank=True)
    entry = models.OneToOneField(FinanceEntry, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='claim', verbose_name='入账记录')
    created_at = models.DateTimeField('提交时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '报销申请'
        verbose_name_plural = '报销申请'

    def __str__(self):
        return f'{self.applicant} 报销 {self.amount}'

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': '金额必须大于 0。'})


class Attachment(models.Model):
    """统一附件表：成果、留言、报销凭证和记账凭证共用一套私有文件与权限检查。"""

    OWNER_FIELDS = ('submission', 'comment', 'claim', 'entry')

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='attachments', verbose_name='成果')
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, null=True, blank=True,
                                related_name='attachments', verbose_name='留言')
    claim = models.ForeignKey(ExpenseClaim, on_delete=models.CASCADE, null=True, blank=True,
                              related_name='attachments', verbose_name='报销申请')
    entry = models.ForeignKey(FinanceEntry, on_delete=models.CASCADE, null=True, blank=True,
                              related_name='attachments', verbose_name='财务记录')
    file = models.FileField('文件', upload_to=private_path, validators=[validate_private_file])
    original_name = models.CharField('原文件名', max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='uploaded_attachments', verbose_name='上传人')
    created_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '附件'
        verbose_name_plural = '附件'

    def __str__(self):
        return self.original_name

    @property
    def owner(self):
        for name in self.OWNER_FIELDS:
            value = getattr(self, name)
            if value is not None:
                return value
        return None

    def clean(self):
        if sum(1 for name in self.OWNER_FIELDS if getattr(self, name)) != 1:
            raise ValidationError('附件必须且只能属于一个成果、留言、报销申请或财务记录。')


def attach_files(owner_field, owner, files, user):
    """把一次上传的多个文件保存为 owner 的附件；owner_field 是 Attachment 上的外键名。"""
    created = []
    for item in files:
        attachment = Attachment(**{owner_field: owner}, file=item,
                                original_name=Path(item.name).name[:255], uploaded_by=user)
        attachment.save()
        created.append(attachment)
    return created


class Announcement(models.Model):
    title = models.CharField('标题', max_length=160)
    body = models.TextField('内容', max_length=5000)
    is_published = models.BooleanField('发布', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class Experiment(models.Model):
    VISIBILITY = [('internal', '内部'), ('pending', '待公开审核'), ('public', '已公开')]
    number = models.CharField('实验编号', max_length=80, unique=True)
    title = models.CharField('实验名称', max_length=160)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True, blank=True, related_name='experiments', verbose_name='关联项目')
    source_id = models.CharField('数据来源标识', max_length=200, blank=True, help_text='如 CNKI 编号；不要粘贴论文全文。')
    batch = models.CharField('实验批次', max_length=120, blank=True)
    model_name = models.CharField('模型', max_length=160, blank=True)
    prompt_version = models.CharField('Prompt 版本', max_length=120, blank=True)
    procedure = models.TextField('实验流程', max_length=10000, blank=True)
    result = models.TextField('结果与分析', max_length=15000, blank=True)
    human_review = models.TextField('人工审核结论', max_length=5000, blank=True)
    github_url = models.URLField('GitHub 链接', blank=True)
    git_ref = models.CharField('Commit 或 Tag', max_length=120, blank=True)
    visibility = models.CharField('公开状态', max_length=10, choices=VISIBILITY, default='internal')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='experiments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']



class PublicProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='public_profile')
    display_name = models.CharField('公开姓名', max_length=80, blank=True)
    research_area = models.CharField('研究方向', max_length=160, blank=True)
    bio = models.TextField('公开简介', max_length=2000, blank=True)
    github_url = models.URLField('公开 GitHub', blank=True)
    is_public = models.BooleanField('展示在成员页', default=False)
    updated_at = models.DateTimeField(auto_now=True)




class TeamContact(models.Model):
    email = models.EmailField('团队邮箱', blank=True)
    phone = models.CharField('联系电话', max_length=40, blank=True)
    github_url = models.URLField('团队 GitHub', blank=True)
    other = models.TextField('其他联系方式', max_length=2000, blank=True)
    description = models.TextField('合作说明', max_length=3000, blank=True)
