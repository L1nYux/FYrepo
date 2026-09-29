import hashlib
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

ALLOWED_EXTENSIONS = {'.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx'}
MAX_FILE_BYTES = 20 * 1024 * 1024


def validate_private_file(value):
    if Path(value.name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError('只允许 TXT、PDF、Word 或 Excel 文件。')
    if value.size > MAX_FILE_BYTES:
        raise ValidationError('单个文件不能超过 20 MB。')


def private_path(instance, filename):
    return f'{instance._meta.model_name}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Invite(models.Model):
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


class Task(models.Model):
    OPEN, SUBMITTED, COMPLETED = 'open', 'submitted', 'completed'
    STATUS = [(OPEN, '进行中'), (SUBMITTED, '待审核'), (COMPLETED, '已结项')]
    title = models.CharField('任务名称', max_length=160)
    description = models.TextField('任务说明')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_tasks', verbose_name='负责人')
    due_date = models.DateField('截止日期')
    progress = models.PositiveSmallIntegerField('进度（0-100）', default=0)
    status = models.CharField('状态', max_length=12, choices=STATUS, default=OPEN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_tasks', verbose_name='发布者')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    archived_at = models.DateTimeField('归档时间', null=True, blank=True)

    class Meta:
        ordering = ['due_date', '-created_at']
        verbose_name = '任务'
        verbose_name_plural = '任务'

    def clean(self):
        if self.progress > 100:
            raise ValidationError({'progress': '进度不能超过 100。'})
        if self.assignee_id and self.assignee.is_staff:
            raise ValidationError({'assignee': '负责人应为开发者账号。'})

    def __str__(self):
        return self.title


class Submission(models.Model):
    PENDING, ACCEPTED, REJECTED = 'pending', 'accepted', 'rejected'
    STATUS = [(PENDING, '待审核'), (ACCEPTED, '已通过'), (REJECTED, '已退回')]
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name='submissions', verbose_name='任务')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name='提交者')
    note = models.TextField('成果说明', max_length=3000)
    attachment = models.FileField('成果文件', upload_to=private_path, validators=[validate_private_file])
    original_name = models.CharField('原文件名', max_length=255)
    status = models.CharField('审核状态', max_length=12, choices=STATUS, default=PENDING)
    review_note = models.TextField('审核意见', blank=True, max_length=3000)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_submissions', verbose_name='审核人')
    reviewed_at = models.DateTimeField('审核时间', null=True, blank=True)
    created_at = models.DateTimeField('提交时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '任务成果'
        verbose_name_plural = '任务成果'


class FinanceEntry(models.Model):
    KIND = [('income', '收入'), ('expense', '支出'), ('bonus', '奖金'), ('api', 'API 成本')]
    kind = models.CharField('类型', max_length=10, choices=KIND)
    amount = models.DecimalField('金额（元）', max_digits=12, decimal_places=2)
    occurred_on = models.DateField('发生日期')
    memo = models.TextField('说明', max_length=3000)
    receipt = models.FileField('凭证', upload_to=private_path, validators=[validate_private_file], blank=True)
    receipt_name = models.CharField('凭证原文件名', max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name='记账人')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    voided_at = models.DateTimeField('作废时间', null=True, blank=True)

    class Meta:
        ordering = ['-occurred_on', '-created_at']
        verbose_name = '财务记录'
        verbose_name_plural = '财务记录'

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': '金额必须大于 0。'})

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount}'


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='操作人')
    action = models.CharField('操作', max_length=80)
    target = models.CharField('对象', max_length=200)
    detail = models.JSONField('详情', default=dict, blank=True)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '操作日志'
        verbose_name_plural = '操作日志'

    @classmethod
    def record(cls, actor, action, target, **detail):
        cls.objects.create(actor=actor, action=action, target=str(target), detail=detail)
