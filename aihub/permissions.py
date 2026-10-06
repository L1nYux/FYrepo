from django.core.exceptions import PermissionDenied
from core import permissions as team_permissions
from .models import PoolSettings


def is_pool_owner(viewer):
    user=team_permissions.user_of(viewer)
    if not user or not user.is_authenticated or not user.is_active or not team_permissions.is_admin(viewer): return False
    return PoolSettings.objects.filter(owner_id=user.pk).exists()


def require_pool_owner(viewer):
    if not is_pool_owner(viewer): raise PermissionDenied('公共 API 池仅限负责人管理。')


def visible_budget(user):
    from .service import summary
    value=summary(user)
    if not is_pool_owner(user):
        value.pop('team',None); value.pop('team_week',None)
    return value
