from django.core.exceptions import PermissionDenied
from . import permissions as perms
from .tenancy import membership_for

CAPABILITIES = [('announcements', '发布与编辑公告'), ('recruitment', 'HR：招募、审核与邀请成员'), ('finance','管理账本和审批报销'), ('api','管理团队 API 池'), ('projects','管理团队项目'), ('experiments','管理团队实验')]


def has_hr(viewer, team):
    """Check the destination team, independently of the currently open workspace."""
    user = perms.user_of(viewer)
    if not user or not user.is_authenticated or not user.is_active or not team:
        return False
    from .models import TeamMembership
    member = TeamMembership.objects.filter(team=team, user=user, active=True,
        deleted_at__isnull=True, team__active=True, user__is_active=True, role__in=['owner','admin','member']).first()
    return bool(member and (member.role == 'owner' or 'recruitment' in member.permissions))


def require_hr_locked(viewer, team):
    """Serialize an HR write with the owner's permission grant/revocation."""
    from django.db import connection
    from django.db.models import F
    from .models import Team
    if not connection.in_atomic_block:
        raise RuntimeError('HR write authorization requires an enclosing transaction.')
    if not team or Team.objects.filter(pk=team.pk,active=True).update(member_limit=F('member_limit'))!=1:
        raise PermissionDenied('团队已不可用。')
    Team.objects.select_for_update().get(pk=team.pk)
    if not has_hr(viewer,team):
        raise PermissionDenied('团队 HR 授权已失效，请重新打开页面。')


def allowed(viewer, permission):
    user=perms.user_of(viewer)
    if not perms.is_team_member(viewer):
        return False
    member=membership_for(user)
    # Legacy invitation endpoints now use the same HR authorization as offers.
    if permission in ('invitations', 'recruitment'):
        return has_hr(user, member.team if member else None)
    return bool(member and member.active and not member.deleted_at and member.team.active and
        (member.role in ('owner','admin') or permission in member.permissions))


def require(viewer, permission):
    if not allowed(viewer, permission):
        raise PermissionDenied('未获得此项团队权限。')


def can_manage_admission(viewer):
    user=perms.user_of(viewer)
    return bool(user.is_authenticated and user.is_active and
        (user.is_superuser or user.has_perm('core.manage_team_admission')))
