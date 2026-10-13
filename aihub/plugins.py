"""One catalog and one setting store for every trusted registered plugin."""
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction
from django.db.models import F
from django.contrib.auth import get_user_model
from .models import AgentPluginSetting
from .tool_registry import registry


def catalog(user,*,include_client=True):
    settings=dict(AgentPluginSetting.objects.filter(user=user).values_list('plugin','enabled'))
    rows=[{'id':plugin.id,'label':plugin.label,'description':plugin.description,'category':plugin.category,
        'icon':plugin.icon,'publisher':plugin.publisher,'version':plugin.version,'builtin':plugin.builtin,
        'enabled':settings.get(plugin.id,plugin.default_enabled),'available':True,'runtime':'server','scope':'account',
        'tools':[{'name':tool.name,'label':tool.label,'description':tool.summary or tool.description,'effect':tool.effect} for tool in plugin.tools],
        'writes':any(tool.effect=='write' for tool in plugin.tools)} for plugin in registry.plugins.values()]
    if include_client:
        from .client_plugins import catalog as client_catalog
        rows+=client_catalog()
    return rows


def set_enabled(user,identifier,enabled):
    if identifier not in registry.plugins or type(enabled) is not bool:
        raise ValidationError('插件选项无效。')
    if not user.is_active:raise PermissionDenied('账户不可用。')
    with transaction.atomic():
        accounts=get_user_model().objects
        accounts.filter(pk=user.pk,is_active=True).update(is_active=F('is_active'))
        if not accounts.filter(pk=user.pk,is_active=True).exists():raise PermissionDenied('账户不可用。')
        AgentPluginSetting.objects.update_or_create(user=user,plugin=identifier,defaults={'enabled':enabled})
    return next(plugin for plugin in catalog(user) if plugin['id']==identifier)
