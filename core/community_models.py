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


class AccountNotice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account_notices')
    application = models.ForeignKey('core.TeamApplication', null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    target_url = models.CharField(max_length=300, blank=True)
    body = models.CharField(max_length=1000, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['user', 'read_at'], name='account_notice_unread')]


class ApplicantProfile(models.Model):
    blocked_teams = models.ManyToManyField('core.Team', blank=True, related_name='talent_blocks')
    listed = models.BooleanField('展示在人才市场', default=False)
    intention = models.CharField('合作意向', max_length=120, blank=True)
    availability = models.CharField('可投入时间', max_length=120, blank=True)
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
    planned_headcount = models.PositiveIntegerField('计划招募人数',null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.CheckConstraint(condition=models.Q(planned_headcount__isnull=True)|models.Q(planned_headcount__gte=1,planned_headcount__lte=1000),name='opening_valid_headcount')]


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
    relation_verified = models.BooleanField(default=False, editable=False)
    legacy_message = models.OneToOneField('core.ChatMessage', null=True, blank=True, on_delete=models.PROTECT, related_name='personal_record')
    sticker = models.ForeignKey('core.Sticker', null=True, blank=True, on_delete=models.PROTECT, related_name='personal_messages')
    references = models.JSONField(default=list, blank=True)
    hidden_by = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='hidden_personal_messages')
    quote = models.JSONField(default=dict, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering=['created_at','pk']
        indexes=[models.Index(fields=['sender','recipient','id'],name='personal_thread_messages')]
        constraints=[models.CheckConstraint(condition=~models.Q(sender=models.F('recipient')),name='personal_message_not_self')]


class ChatGroup(models.Model):
    team = models.ForeignKey('core.Team', null=True, blank=True, on_delete=models.PROTECT, related_name='chat_groups')
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    name = models.CharField(max_length=80)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='owned_chat_groups')
    announcement = models.TextField(max_length=4000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        constraints=[models.UniqueConstraint(fields=['team'],condition=models.Q(is_default=True),name='one_default_team_group')]


class GroupMember(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.PROTECT, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='chat_group_memberships')
    muted = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    show_nicknames = models.BooleanField(default=True)
    nickname = models.CharField(max_length=80, blank=True)
    remark = models.CharField(max_length=80, blank=True)
    admin = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['group','user'],name='one_chat_group_membership')]


class GroupMessage(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.PROTECT, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='group_messages')
    body = models.TextField(max_length=2000)
    sticker = models.ForeignKey('core.Sticker', null=True, blank=True, on_delete=models.PROTECT, related_name='group_messages')
    references = models.JSONField(default=list, blank=True)
    hidden_by = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='hidden_group_messages')
    quote = models.JSONField(default=dict, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering=['created_at','pk']
        indexes=[models.Index(fields=['group','id'],name='group_thread_messages')]


class MessageUpload(models.Model):
    personal = models.ForeignKey(PersonalMessage, null=True, blank=True, on_delete=models.PROTECT, related_name='uploads')
    message = models.ForeignKey(GroupMessage, null=True, blank=True, on_delete=models.PROTECT, related_name='uploads')
    file = models.FileField(upload_to='message-uploads/%Y/%m/')
    original_name = models.CharField(max_length=255)
    class Meta:
        constraints=[models.CheckConstraint(condition=(models.Q(personal__isnull=False,message__isnull=True)|models.Q(personal__isnull=True,message__isnull=False)), name='upload_one_message')]
