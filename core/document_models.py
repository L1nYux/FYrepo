"""Private documents, approved editing grants and immutable published versions."""
import uuid
from django.conf import settings
from django.db import models


def document_file(instance, filename):
    from pathlib import Path
    return 'documents/' + uuid.uuid4().hex + Path(filename).suffix.lower()


class SharedDocument(models.Model):
    workspace = models.ForeignKey('core.Workspace', on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_documents')
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=[('online','在线文档'),('docx','Word'),('xlsx','Excel'),('pdf','PDF')], default='online')
    purpose = models.CharField(max_length=12, choices=[('notes','资料'),('plan','规划'),('result','成果')], default='notes')
    project = models.ForeignKey('core.Project', null=True, blank=True, on_delete=models.PROTECT, related_name='documents')
    task = models.ForeignKey('core.Task', null=True, blank=True, on_delete=models.PROTECT, related_name='documents')
    competition = models.ForeignKey('core.Competition', null=True, blank=True, on_delete=models.PROTECT, related_name='documents')
    experiment = models.ForeignKey('core.Experiment', null=True, blank=True, on_delete=models.PROTECT, related_name='documents')
    current = models.ForeignKey('core.DocumentVersion', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-updated_at','-pk']
        constraints = [models.CheckConstraint(condition=(
            models.Q(project__isnull=True,task__isnull=True,competition__isnull=True) |
            models.Q(project__isnull=True,task__isnull=True,experiment__isnull=True) |
            models.Q(project__isnull=True,competition__isnull=True,experiment__isnull=True) |
            models.Q(task__isnull=True,competition__isnull=True,experiment__isnull=True)), name='document_one_context')]


class DocumentVersion(models.Model):
    document = models.ForeignKey(SharedDocument, on_delete=models.PROTECT, related_name='versions')
    number = models.PositiveIntegerField()
    content = models.JSONField(default=dict)
    file = models.FileField(upload_to=document_file, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    summary = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def save(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('正式版本不可覆盖，请创建并审核修改稿。')
        return super().save(*args,**kwargs)
    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['document','number'], name='document_unique_version')]


class DocumentAccess(models.Model):
    document = models.ForeignKey(SharedDocument, on_delete=models.PROTECT, related_name='access')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='document_access')
    role = models.CharField(max_length=12, choices=[('viewer','查看'),('commenter','评论'),('editor','创建修改稿'),('reviewer','审核')], default='viewer')
    active = models.BooleanField(default=True)
    membership_required = models.BooleanField(default=False)
    project_required = models.BooleanField(default=False)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['document','user'], name='document_unique_access')]


class DocumentEditRequest(models.Model):
    document = models.ForeignKey(SharedDocument, on_delete=models.PROTECT, related_name='edit_requests')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=12, choices=[('pending','待批准'),('approved','已批准'),('rejected','未批准')], default='pending')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['document','user'], condition=models.Q(state='pending'), name='document_pending_edit_request')]


class DocumentDraft(models.Model):
    document = models.ForeignKey(SharedDocument, on_delete=models.PROTECT, related_name='drafts')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='document_drafts')
    base = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='+')
    content = models.JSONField(default=dict)
    file = models.FileField(upload_to=document_file, blank=True)
    generation = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=20, choices=[('draft','修改中'),('submitted','待审核'),('changes_requested','需要调整'),('merged','已采纳'),('rejected','未采纳')], default='draft')
    summary = models.CharField(max_length=500, blank=True)
    review_note = models.CharField(max_length=1000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-updated_at','-pk']
        constraints = [models.UniqueConstraint(fields=['document','author'], condition=models.Q(state__in=['draft','submitted','changes_requested']), name='document_one_open_draft')]


class DocumentComment(models.Model):
    document = models.ForeignKey(SharedDocument, on_delete=models.PROTECT, related_name='comments')
    draft = models.ForeignKey(DocumentDraft, null=True, blank=True, on_delete=models.PROTECT, related_name='comments')
    version = models.ForeignKey(DocumentVersion, null=True, blank=True, on_delete=models.PROTECT, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    anchor = models.CharField(max_length=300, blank=True)
    body = models.TextField(max_length=4000)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at','pk']


class OfficeEditingSession(models.Model):
    key = models.UUIDField(default=uuid.uuid4, unique=True)
    draft = models.ForeignKey(DocumentDraft, on_delete=models.PROTECT, related_name='office_sessions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    generation = models.PositiveIntegerField()
    closed = models.BooleanField(default=False)
    save_requested = models.UUIDField(null=True)
    save_completed = models.UUIDField(null=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class DocumentImage(models.Model):
    document = models.ForeignKey(SharedDocument, on_delete=models.PROTECT)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    file = models.FileField(upload_to=document_file)


class DocumentPlan(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    version = models.ForeignKey(DocumentVersion,on_delete=models.PROTECT,related_name='plans')
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    billing_workspace = models.ForeignKey('core.Workspace',null=True,on_delete=models.PROTECT)
    model_id_used = models.PositiveBigIntegerField(null=True)
    state = models.CharField(max_length=12,default='new',choices=[('new','待生成'),('running','生成中'),('ready','待确认'),('error','未完成'),('applied','已创建')])
    plan = models.JSONField(default=dict)
    error = models.CharField(max_length=1000,blank=True)
    call_id = models.UUIDField(null=True)
    project = models.OneToOneField('core.Project',null=True,on_delete=models.PROTECT,related_name='plan_import')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['version','user'],name='document_one_plan_preview')]


class TaskDependency(models.Model):
    task = models.ForeignKey('core.Task',on_delete=models.PROTECT,related_name='dependencies')
    prerequisite = models.ForeignKey('core.Task',on_delete=models.PROTECT,related_name='dependents')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['task','prerequisite'],name='task_unique_dependency'),models.CheckConstraint(condition=~models.Q(task=models.F('prerequisite')),name='task_dependency_not_self')]


class DocumentSubmission(models.Model):
    submission = models.ForeignKey('core.Submission',on_delete=models.PROTECT,related_name='document_versions')
    version = models.ForeignKey(DocumentVersion,on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['submission','version'],name='submission_unique_document_version')]
