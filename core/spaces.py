"""Personal and organization workspaces; membership is never an account role."""
from django.db import models
from django.conf import settings


class Workspace(models.Model):
    kind = models.CharField(max_length=12, choices=[('personal', '个人空间'), ('team', '团队公账户')])
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='personal_workspace')
    team = models.OneToOneField('core.Team', null=True, blank=True, on_delete=models.PROTECT, related_name='workspace')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(kind='personal', owner__isnull=False, team__isnull=True) | models.Q(kind='team', owner__isnull=True, team__isnull=False)), name='workspace_exact_owner')]

    @property
    def name(self):
        return self.team.name if self.team_id else '个人空间'


class PlatformAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='platform_actions')
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='account_events')
    action = models.CharField(max_length=30)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        permissions = [('manage_platform_accounts', '封禁和注销平台账号')]


class WorkspaceEvent(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workspace_events')
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    action = models.CharField(max_length=20)
    authority = models.JSONField(default=dict)
    fields = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class RegistrationChallenge(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    address_hash = models.CharField(max_length=64, db_index=True)
    email = models.EmailField()
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RegistrationThrottle(models.Model):
    address_hash = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField()
    count = models.PositiveSmallIntegerField(default=0)
