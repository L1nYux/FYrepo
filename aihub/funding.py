"""Payer choice never changes conversation ownership or data permissions."""
from django.core.exceptions import PermissionDenied,ValidationError
from core.resource_navigation import spaces
from core.tenancy import scope


def choices(user):
    from .models import Allowance
    values=[]
    for space in spaces(user):
        if space.kind=='team' and Allowance.all_objects.filter(workspace=space,user=user,enabled=False).exists():continue
        values.append(space)
    return values


def resolve(user,identifier=None):
    if identifier in (None,'','personal'):
        result=spaces(user).filter(kind='personal').first()
    elif str(identifier).isascii() and str(identifier).isdigit() and len(str(identifier))<=18:
        result=spaces(user).filter(pk=identifier).first()
    else:raise ValidationError('请选择有效的扣费来源。')
    if not result:raise PermissionDenied('该扣费来源的授权已失效，请选择个人 API 池或其他团队。')
    check(user,result)
    return result


def check(user,space):
    from .service import require_member
    from .models import Allowance
    if not space or not space.active:raise PermissionDenied('扣费来源已关闭。')
    with scope(space):
        require_member(user)
        if Allowance.objects.filter(user=user,enabled=False).exists():raise PermissionDenied('你在此 API 池的使用资格已被停用，请切换扣费来源。')


def catalog(user,space):
    from .views import model_catalog
    from .permissions import visible_budget
    with scope(space):
        check(user,space)
        return {'models':model_catalog(user),'budget':visible_budget(user),'funding':space.pk,'funding_name':space.name}
