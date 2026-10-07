"""Explicit, recipient-confirmed cooperation; never grants software privileges."""
from django.conf import settings
from django.db import models


class RecruitmentOffer(models.Model):
    team = models.ForeignKey('core.Team', on_delete=models.PROTECT, related_name='offers')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recruitment_offers')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='issued_offers')
    project = models.ForeignKey('core.Project', null=True, blank=True, on_delete=models.PROTECT, related_name='offers')
    title = models.CharField('职位或合作名称', max_length=120)
    terms = models.TextField('负责事项与合作条件', max_length=4000)
    state = models.CharField(max_length=12, default='pending', choices=[('pending','待回应'),('accepted','已接受'),('declined','已拒绝'),('withdrawn','已撤销'),('expired','已过期')])
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-created_at','-pk']
        constraints = [models.UniqueConstraint(fields=['team','recipient'], condition=models.Q(state='pending'), name='one_pending_team_offer')]


class ProjectCollaborator(models.Model):
    project = models.ForeignKey('core.Project', on_delete=models.PROTECT, related_name='collaborations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='project_collaborations')
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    offer = models.OneToOneField(RecruitmentOffer, null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['project','user'], name='one_project_collaborator')]
