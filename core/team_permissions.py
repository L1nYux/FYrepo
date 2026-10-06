from django.core.exceptions import PermissionDenied
from . import permissions as perms
from .tenancy import membership_for

CAPABILITIES = [('announcements', '发布与编辑公告'), ('invitations', '发放成员邀请码'), ('recruitment', '维护团队广场与审核申请'), ('finance','管理账本和审批报销'), ('api','管理团队 API 池'), ('projects','管理团队项目'), ('experiments','管理团队实验')]


def allowed(viewer, permission):
    user=perms.user_of(viewer)
    if not perms.is_team_member(viewer):
        return False
    member=membership_for(user)
    return bool(member and member.active and not member.deleted_at and member.team.active and
        (member.role in ('owner','admin') or permission in member.permissions))


def require(viewer, permission):
    if not allowed(viewer, permission):
        raise PermissionDenied('未获得此项团队权限。')


def can_manage_admission(viewer):
    user=perms.user_of(viewer)
    return bool(user.is_authenticated and user.is_active and
        (user.is_superuser or user.has_perm('core.manage_team_admission')))
