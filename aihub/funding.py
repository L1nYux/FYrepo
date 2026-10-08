"""Payer choice never changes conversation ownership or data permissions."""
from django.core.exceptions import PermissionDenied,ValidationError
from core.resource_navigation import spaces
from core.tenancy import scope


def choices(user):
    from .models import Allowance
    values=[]
    for space in spaces(user).filter(kind='team'):
        if space.kind=='team' and Allowance.all_objects.filter(workspace=space,user=user,enabled=False).exists():continue
        values.append(space)
    return values


def resolve(user,identifier=None):
    if str(identifier).isascii() and str(identifier).isdigit() and len(str(identifier))<=18:
        result=spaces(user).filter(kind='team',pk=identifier).first()
    else:raise ValidationError('请选择有效的扣费来源。')
    if not result:raise PermissionDenied('该团队的授权已失效，请选择获授权团队。')
    check(user,result)
    return result


def check(user,space):
    from .service import require_member
    from .models import Allowance
    if not space or space.kind!='team' or not space.active:raise PermissionDenied('请选择获授权团队的 API 池。')
    with scope(space):
        require_member(user)
        if Allowance.objects.filter(user=user,enabled=False).exists():raise PermissionDenied('你在此 API 池的使用资格已被停用，请切换扣费来源。')


def select_team(request):
    """Select a team API workspace without changing private conversation ownership."""
    from core.message_scope import select
    name=request.resolver_match.url_name if request.resolver_match else ''
    identifier=request.GET.get('funding') if name in ('api_catalog','me_api') and request.GET.get('funding') else request.POST.get('ownership') or request.GET.get('ownership')
    available=spaces(request.user).filter(kind='team')
    if identifier is not None:
        if not str(identifier).isascii() or not str(identifier).isdigit() or len(str(identifier))>18:
            raise PermissionDenied('请选择有效团队。')
        selected=available.filter(pk=identifier).first()
        if not selected:raise PermissionDenied('无权访问该团队 API 池。')
    else:
        current=getattr(request,'workspace',None)
        selected=available.filter(pk=current.pk).first() if current else None
        selected=selected or available.filter(team_id=request.session.get('workbench-team')).first() or available.order_by('pk').first()
    if selected:
        select(request,selected.pk)
        if name in ('api_pool','api_manage') and identifier is not None and request.method=='GET':
            request.session['workbench-team']=selected.team_id
            request.session['workbench-space']='team:'+str(selected.team_id)
    return selected


def catalog(user,space):
    from .views import model_catalog
    from .permissions import visible_budget
    with scope(space):
        check(user,space)
        return {'models':model_catalog(user),'budget':visible_budget(user),'funding':space.pk,'funding_name':space.name}
