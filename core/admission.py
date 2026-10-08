"""One invitation redemption path for web, desktop and existing accounts."""
import hashlib
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import Team, TeamMembership, Invite, TeamCreationInvite, MemberProfile
from .tenancy import scope


def lock_capacity(team):
    # A write serializes admission on SQLite as well as row-locking databases.
    Team.objects.filter(pk=team.pk, active=True).update(member_limit=F('member_limit'))
    team.refresh_from_db()
    if not team.active:
        raise ValidationError('团队已停用。')
    if TeamMembership.objects.filter(team=team, active=True, deleted_at__isnull=True).count() >= team.member_limit:
        raise ValidationError('团队人数已达上限，请联系团队管理员。')


def valid_invitation(code, user=None, *, lock=False):
    digest = hashlib.sha256(str(code).strip().encode()).hexdigest()
    conditions = dict(code_hash=digest, used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())
    if lock:
        TeamCreationInvite.objects.filter(code_hash=digest).update(code_hash=F('code_hash'))
        Invite.all_objects.filter(code_hash=digest).update(code_hash=F('code_hash'))
    creation = TeamCreationInvite.objects.filter(**conditions).first()
    if creation:
        return creation
    member = Invite.all_objects.filter(**conditions, team__active=True).select_related('team').first()
    if member and (not member.restricted_user_id or user and member.restricted_user_id == user.pk):
        return member
    raise ValidationError('邀请码无效、已使用、已撤销或已过期。')


def create_team(user, name, member_limit=None):
    name=str(name).strip()
    if not name or len(name)>100:
        raise ValidationError('团队名称须为 1–100 字。')
    if not user.is_active:
        raise ValidationError('账号不可用。')
    with transaction.atomic():
        team=Team.objects.create(name=name,owner=user,member_limit=member_limit or getattr(settings,'WORKBENCH_DEFAULT_TEAM_LIMIT',10))
        TeamMembership.objects.create(team=team,user=user,role='owner')
        with scope(team):
            from aihub.models import PoolSettings
            from .models import TeamContact
            PoolSettings.objects.create(owner=user)
            TeamContact.objects.create()
        return team


def create_from_invitation(user, code, name):
    with transaction.atomic():
        invite=valid_invitation(code,user,lock=True)
        if not isinstance(invite,TeamCreationInvite):
            raise ValidationError('请使用创建团队邀请码。')
        now=timezone.now()
        if TeamCreationInvite.objects.filter(pk=invite.pk,used_at__isnull=True,revoked_at__isnull=True,expires_at__gt=now).update(used_at=now,used_by=user)!=1:
            raise ValidationError('邀请码已被使用。')
        team=create_team(user,name,invite.member_limit)
        TeamCreationInvite.objects.filter(pk=invite.pk).update(created_team=team)
        return team


def join_from_invitation(user, code=None, invite=None):
    with transaction.atomic():
        if invite is not None:
            Invite.all_objects.filter(pk=invite.pk).update(code_hash=F('code_hash'))
        invite = valid_invitation(code, user, lock=True) if invite is None else Invite.all_objects.filter(pk=invite.pk, used_at__isnull=True,
            revoked_at__isnull=True, expires_at__gt=timezone.now(), team__active=True, restricted_user=user).select_related('team').first()
        if not isinstance(invite, Invite):
            raise ValidationError('请使用有效的成员邀请码。')
        lock_capacity(invite.team)
        from .models import TeamApplication
        application=TeamApplication.objects.select_for_update().select_related('opening').filter(invite=invite).first()
        if application:
            if application.state!='accepted' or application.applicant_id!=user.pk:raise ValidationError('这份招聘申请已不可用于入队。')
            from .recruitment import lock_opening
            lock_opening(application.opening)
        old=TeamMembership.objects.filter(team=invite.team,user=user).first()
        if old and not old.deleted_at:
            raise ValidationError('你已在该团队中，或资格被停用，请联系团队管理员。')
        now=timezone.now()
        if Invite.all_objects.filter(pk=invite.pk, used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now).update(used_at=now, used_by=user)!=1:
            raise ValidationError('邀请码已被使用。')
        TeamMembership.objects.update_or_create(team=invite.team,user=user,defaults={'role':'member','active':True,'deleted_at':None,'position':'','permissions':[]})
        if application:
            application.state='joined';application.save(update_fields=['state','updated_at'])
            from .recruitment import finish_opening
            finish_opening(application.opening)
        return invite.team


def register_account(form):
    with transaction.atomic():
        code=form.cleaned_data.get('invite_code', '')
        invite=valid_invitation(code, lock=True) if code else None
        user=form.save(commit=False)
        user.is_staff=user.is_superuser=False
        user.save()
        MemberProfile.objects.update_or_create(user=user, defaults={'tier':MemberProfile.DEVELOPER if invite else MemberProfile.NORMAL,
            'workbench_id':user.username,'nickname':form.cleaned_data.get('nickname','') or user.username})
        team=create_from_invitation(user, code, form.cleaned_data.get('team_name','')) if isinstance(invite,TeamCreationInvite) else join_from_invitation(user,code) if invite else None
        return user, team


def admit_member(user,team,position=''):
    """Admission after a voluntary application or a recipient-accepted offer."""
    if not user.is_active:raise ValidationError('个人账号已不可用。')
    with transaction.atomic():
        Team.objects.filter(pk=team.pk).update(active=F('active'))
        old=TeamMembership.objects.filter(team=team,user=user).first()
        if old and not old.deleted_at and old.role in ('owner','admin','member'):
            if not old.active:raise ValidationError('成员资格已停用，请先联系团队管理员。')
            return old
        lock_capacity(team)
        member,_=TeamMembership.objects.update_or_create(team=team,user=user,defaults={'role':'member','active':True,'deleted_at':None,'position':position[:60],'permissions':[]})
        return member
