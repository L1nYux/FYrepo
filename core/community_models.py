"""Account-level admission and opt-in recruitment, independent of private workspaces."""
import hashlib
import secrets
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone


class TeamCreationInvite(models.Model):
    code_hash = models.CharField(max_length=64, unique=True)
    member_limit = models.PositiveIntegerField(default=10)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='issued_team_creation_invites')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='redeemed_team_creation_invites')
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_team = models.OneToOneField('core.Team', null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-created_at', '-pk']
        permissions = [('manage_team_admission', '管理团队准入及规模')]

    @classmethod
    def issue(cls, user, member_limit=10, days=7):
        code = secrets.token_urlsafe(24)
        item = cls.objects.create(created_by=user, member_limit=member_limit,
            code_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=timezone.now()+timedelta(days=days))
        return item, code

    @property
    def state(self):
        return '已使用' if self.used_at else '已撤销' if self.revoked_at else '已过期' if self.expires_at <= timezone.now() else '可使用'


class ApplicantProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='applicant_profile')
    introduction = models.TextField(max_length=4000, blank=True)
    skills = models.CharField(max_length=500, blank=True)
    portfolio = models.URLField(max_length=1000, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class TeamOpening(models.Model):
    team = models.ForeignKey('core.Team', on_delete=models.PROTECT, related_name='openings')
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=4000)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class TeamApplication(models.Model):
    STATES = [('pending', '待审核'), ('accepted', '已接受'), ('rejected', '未通过'), ('withdrawn', '已撤回'), ('joined', '已加入')]
    opening = models.ForeignKey(TeamOpening, on_delete=models.PROTECT, related_name='applications')
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='team_applications')
    resume = models.TextField(max_length=5000)
    portfolio = models.URLField(max_length=1000, blank=True)
    note = models.TextField(max_length=1000, blank=True)
    state = models.CharField(max_length=12, choices=STATES, default='pending')
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='reviewed_team_applications')
    invite = models.OneToOneField('core.Invite', null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['opening', 'applicant'], name='one_application_per_opening')]


class FriendRequest(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sent_friend_requests')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='received_friend_requests')
    note = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=12, choices=[('pending','待处理'),('accepted','已接受'),('rejected','已拒绝')], default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['sender','recipient'],condition=models.Q(state='pending'),name='one_pending_friend_request'),
            models.CheckConstraint(condition=~models.Q(sender=models.F('recipient')),name='friend_request_not_self')]


class Friendship(models.Model):
    first = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='first_friendships')
    second = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='second_friendships')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['first','second'],name='one_friendship_pair'),
            models.CheckConstraint(condition=models.Q(first__lt=models.F('second')),name='ordered_friendship_pair')]


class PersonalMessage(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sent_personal_messages')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='received_personal_messages')
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering=['created_at','pk']
        indexes=[models.Index(fields=['sender','recipient','id'],name='personal_thread_messages')]
        constraints=[models.CheckConstraint(condition=~models.Q(sender=models.F('recipient')),name='personal_message_not_self')]


class ChatGroup(models.Model):
    team = models.ForeignKey('core.Team', on_delete=models.PROTECT, related_name='chat_groups')
    name = models.CharField(max_length=80)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='owned_chat_groups')
    created_at = models.DateTimeField(auto_now_add=True)


class GroupMember(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.PROTECT, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='chat_group_memberships')
    admin = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['group','user'],name='one_chat_group_membership')]


class GroupMessage(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.PROTECT, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='group_messages')
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering=['created_at','pk']
        indexes=[models.Index(fields=['group','id'],name='group_thread_messages')]
