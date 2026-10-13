from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied,ValidationError
from django.http import JsonResponse,Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET,require_POST
from .plugins import catalog,set_enabled
from .views import json_errors,json_body


def account(view):
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        if not request.user.is_authenticated:
            if view.__name__ in ('setting','state'):return JsonResponse({'error':'请先登录知域。'},status=401)
            return redirect_to_login(request.get_full_path())
        if not request.user.is_active:raise PermissionDenied('账户不可用。')
        return view(request,*args,**kwargs)
    wrapper.expects_json=view.__name__ in ('setting','state')
    return wrapper


@account
@never_cache
@require_GET
def marketplace(request,plugin_id=None):
    from core.identity import account_id
    plugins=catalog(request.user)
    plugin=next((row for row in plugins if row['id']==plugin_id),None) if plugin_id else None
    if plugin_id and plugin is None:raise Http404
    query=request.GET.get('q','').strip()[:100]
    selected=request.GET.get('view','all')
    if selected not in ('all','enabled'):selected='all'
    rows=[row for row in plugins if (selected!='enabled' or row['enabled']) and
        (not query or query.casefold() in ' '.join([row['label'],row['description'],row['category'],*[tool['label'] for tool in row['tools']]]).casefold())]
    market_plugins=[{**row,'filtered_out':row not in rows} for row in plugins]
    return render(request,'aihub/plugin_detail.html' if plugin else 'aihub/plugins.html',
        {'plugins':rows,'market_plugins':market_plugins,'plugin':plugin,'client_account':account_id(request.user),'plugin_query':query,'plugin_view':selected,'plugin_enabled_count':sum(row['enabled'] is True for row in plugins),
         'plugin_count':len(plugins),'frontend_features':['plugins']})


@account
@never_cache
@require_POST
@json_errors
def setting(request,plugin_id):
    data=json_body(request)
    if set(data)!={'enabled'}:raise ValidationError('只支持修改插件启用状态。')
    value=set_enabled(request.user,plugin_id,data['enabled'])
    return JsonResponse({'plugin':value})


@account
@never_cache
@require_GET
def state(request):
    return JsonResponse({'account_id':str(request.user.pk),'plugins':catalog(request.user)})
