"""Stable public model names over explicitly configured, tenant-scoped channels."""
import random
from django.db.models import Q
from .models import PoolModel
from .prices import current_price
from .relay import RelayError

def public_name(model):return model.public_alias or str(model.provider_id)+'/'+model.model_id

def weighted_order(models,limit=None):
    remaining=list(models);result=[]
    while remaining and (limit is None or len(result)<limit):
        priority=min(model.route_priority for model in remaining)
        tier=[model for model in remaining if model.route_priority==priority]
        chosen=random.choices(tier,weights=[model.route_weight for model in tier],k=1)[0]
        result.append(chosen);remaining.remove(chosen)
    return result

def resolve_model(user,name,token,*,protocol=None,limit=None):
    from .service import require_member,provider_key
    require_member(user)
    if not isinstance(name,str):raise RelayError('需要有效的模型 ID。')
    query=Q(public_alias=name)|Q(model_id=name)
    prefix,separator,identifier=name.partition('/')
    if separator and prefix.isdecimal():query|=Q(provider_id=int(prefix),model_id=identifier)
    models=list(PoolModel.objects.filter(query,enabled=True,provider__enabled=True).select_related('provider'))
    grouped=[model for model in models if model.public_alias and model.public_alias==name]
    matches=grouped or [model for model in models if name in (str(model.provider_id)+'/'+model.model_id,model.model_id)]
    if not grouped and len(matches)!=1:raise RelayError('模型不存在或存在同名，请使用 /models 返回的模型 ID。')
    allowed=[model for model in matches if not token.allowed_models or model.pk in token.allowed_models]
    if matches and not allowed:raise RelayError('这个 Key 未获授权使用该模型。','model_not_allowed',403)
    ready=[model for model in allowed if (protocol is None or model.provider.protocol==protocol)
           and (type(limit) is not int or limit<=model.max_output_tokens)
           and (not grouped or current_price(model) is not None and provider_key(model.provider))]
    if not ready:raise RelayError('没有支持本次接口和输出上限的已配置渠道。','model_unavailable',503)
    return weighted_order(ready,1)[0]
