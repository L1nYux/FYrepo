import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from decimal import Decimal, ROUND_UP
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from core import permissions as perms
from core.models import Project, Experiment
from .models import Provider, PoolModel, PoolSettings, Allowance, BudgetMonth, BudgetWeek, Call, MemberToken, PointGrant
from .prices import current_price
from .providers import invoke
from .network import TransportError

Q8=Decimal('0.00000001')


def grant_points(user, issuer, points, grant_id):
    from .permissions import is_pool_owner
    if not is_pool_owner(issuer): raise PermissionDenied('仅 API 池负责人可以发放点数。')
    if not perms.is_team_member(user) or not user.is_active: raise ValidationError('请选择有效团队成员。')
    amount = (points / 100).quantize(Q8)
    if amount <= 0: raise ValidationError('发放点数必须大于零。')
    config = pool_settings()
    with transaction.atomic():
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        existing = PointGrant.objects.filter(pk=grant_id).first()
        if existing:
            if existing.user_id != user.pk or existing.issued_by_id != issuer.pk or existing.amount_cny != amount:
                raise ValidationError('发放请求已变化，请刷新页面。')
            return False
        member = allowance(user)
        PointGrant.objects.create(id=grant_id, user=user, issued_by=issuer, amount_cny=amount)
        Allowance.objects.filter(pk=member.pk).update(extra_balance=F('extra_balance') + amount)
    return True


def secret_path(): return Path(settings.DATA_DIR)/'api-pool-keys.json'


def provider_key(provider):
    if provider.key_env: return os.environ.get(provider.key_env,'')
    try: return json.loads(secret_path().read_text('utf-8')).get(str(provider.pk),'')
    except (OSError,ValueError): return ''


def store_key(provider, value):
    if not value: return
    target=secret_path()
    # SQLite write lock also serializes key updates made by different WSGI workers.
    with transaction.atomic():
        Provider.objects.filter(pk=provider.pk).update(enabled=provider.enabled)
        try: values=json.loads(target.read_text('utf-8'))
        except FileNotFoundError: values={}
        values[str(provider.pk)]=value
        fd,name=tempfile.mkstemp(prefix='.pool-key-',dir=target.parent)
        try:
            os.chmod(name,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as output: json.dump(values,output)
            os.replace(name,target)
            os.chmod(target,0o600)
        finally:
            if os.path.exists(name): os.unlink(name)


def require_member(user):
    # Resolve again on each model call so account suspension/removal takes effect during an agent run.
    user.refresh_from_db()
    if not user.is_active or not perms.is_team_member(user): raise PermissionDenied('当前账户无权使用团队 API 池。')
    return user


def pool_settings():
    return PoolSettings.objects.get_or_create(pk=1)[0]


def allowance(user):
    config=pool_settings()
    return Allowance.objects.get_or_create(user=user,defaults={'monthly_limit':config.default_member_limit,'weekly_limit':config.default_weekly_limit})[0]


def reset_member_plans():
    """Refresh all active members' base plan; keep supplemental balances and billing."""
    from django.contrib.auth import get_user_model
    with transaction.atomic():
        PoolSettings.objects.filter(pk=1).update(enabled=F('enabled'))
        for user in get_user_model().objects.filter(is_active=True):
            if perms.is_team_member(user): reset_budget('user:'+str(user.pk),'week')


def month_now(): return timezone.localdate().replace(day=1)


def week_now():
    today=timezone.localdate()
    return today-timedelta(days=today.weekday())


def summary(user):
    config=pool_settings(); member=allowance(user); month=month_now(); week=week_now()
    def bucket(model, period, scope, limit):
        row=model.objects.filter(scope=scope,**{period:week if period=='week' else month}).first()
        actual=row.spent if row else Decimal('0'); reserved=row.reserved if row else Decimal('0')
        spent=max(Decimal('0'),actual-(row.reset_credit if row else Decimal('0')))
        remaining=max(Decimal('0'),limit-spent-reserved) if limit is not None else None
        used_pct=min(100,max(0,float((spent+reserved)/limit*100))) if limit else (100 if limit==0 else 0)
        value = {'spent':str(spent.quantize(Decimal('.0001'))),'actual_spent':str(actual.quantize(Decimal('.0001'))),
            'reserved':str(reserved.quantize(Decimal('.0001'))),'limit':str(limit) if limit is not None else None,
            'remaining':str(remaining.quantize(Decimal('.0001'))) if remaining is not None else None,
            'used_percent':round(used_pct,1),'remaining_percent':round(100-used_pct,1) if limit is not None else None,
            'reset_at':row.reset_at.isoformat() if row and row.reset_at else None}
        for name, amount in [('spent', spent), ('reserved', reserved), ('limit', limit), ('remaining', remaining)]:
            value[name + '_points'] = str((amount * 100).quantize(Decimal('.000001'))) if amount is not None else None
        return value
    next_month=(month.replace(day=28)+timedelta(days=4)).replace(day=1)
    reset_time=lambda date:timezone.make_aware(datetime.combine(date,day_time.min)).isoformat()
    return {'member':bucket(BudgetMonth,'month','user:'+str(user.pk),None),
        'team':bucket(BudgetMonth,'month','team',config.monthly_limit),
        'member_week':bucket(BudgetWeek,'week','user:'+str(user.pk),config.default_weekly_limit),
        'team_week':bucket(BudgetWeek,'week','team',config.weekly_limit),
        'enabled':config.enabled and member.enabled,'month':str(month),'week':str(week),
        'extra': {'balance_points':str(member.extra_balance * 100),
            'reserved_points':str(member.extra_reserved * 100),
            'remaining_points':str(max(Decimal('0'),member.extra_balance-member.extra_reserved) * 100)},
        'preferred_model':member.preferred_model_id,
        'next_week_at':reset_time(week+timedelta(days=7)),'next_month_at':reset_time(next_month)}


def reset_budget(scope, period='both'):
    if period not in ('week','month','both'): raise ValidationError('重置周期无效。')
    config=pool_settings()
    with transaction.atomic():
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        for model,field,start in ((BudgetWeek,'week',week_now()),(BudgetMonth,'month',month_now())):
            if period not in (field,'both'): continue
            row=model.objects.get_or_create(scope=scope,**{field:start})[0]
            model.objects.filter(pk=row.pk).update(reset_credit=F('spent'),reset_at=timezone.now())


def create_token(user,label):
    require_member(user)
    if MemberToken.objects.filter(user=user,revoked_at__isnull=True).count()>=10:
        raise ValidationError('最多保留 10 个调用凭证，请先撤销不用的凭证。')
    token='fy_'+secrets.token_urlsafe(32)
    MemberToken.objects.create(user=user,label=label[:80] or '个人调用',prefix=token[:12],digest=hashlib.sha256(token.encode()).hexdigest())
    return token


def context_objects(project_id=None,experiment_id=None):
    project=None; experiment=None
    if project_id:
        project=Project.objects.filter(pk=project_id,archived_at__isnull=True).first()
        if not project: raise ValidationError('关联项目不可用。')
    if experiment_id:
        experiment=Experiment.objects.filter(pk=experiment_id).first()
        if not experiment or experiment.project_id and experiment.project.archived_at: raise ValidationError('实验记录不可用。')
        if project and experiment.project_id and experiment.project_id!=project.pk: raise ValidationError('实验与项目不一致。')
        if not project: project=experiment.project
    return project,experiment


def reserve(user,model,messages,tools,limit,purpose,group_id,project,experiment):
    require_member(user); config=pool_settings(); member=allowance(user)
    if not config.enabled or not member.enabled: raise ValidationError('API 池或你的调用权限已暂停。')
    if not model.enabled or not model.provider.enabled: raise ValidationError('该厂商或模型已停用。')
    if not provider_key(model.provider): raise ValidationError('管理员尚未配置该厂商的密钥。')
    price=current_price(model)
    if not price: raise ValidationError('该模型尚未登记有效价格。')
    # UTF-8 byte count is a deliberately conservative input allowance, including tools and overhead.
    size=len(json.dumps({'messages':messages,'tools':tools},ensure_ascii=False).encode('utf-8'))
    if size>200000: raise ValidationError('本次上下文过长，请减少引用或开始新对话。')
    input_ceiling=size+2048
    amount=((Decimal(input_ceiling)*max(price.input_rate,price.cached_rate,price.cache_write_rate)+Decimal(limit)*price.output_rate)/1000000*price.cny_exchange_rate).quantize(Q8,rounding=ROUND_UP)
    if amount>config.max_call_cost: raise ValidationError('本次调用预留费用超过单次上限，请减少上下文或输出长度。')
    month=month_now(); week=week_now()
    with transaction.atomic():
        # Take the writer lock before reads inside the transaction, avoiding SQLite read-to-write races.
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        config.refresh_from_db(); member.refresh_from_db()
        if not config.enabled or not member.enabled: raise ValidationError('API 池或你的调用权限已暂停。')
        windows=[(BudgetMonth,'month',month,config.monthly_limit,None,'本月'),
                 (BudgetWeek,'week',week,config.weekly_limit,config.default_weekly_limit,'本周')]
        buckets=[]; basic_available=amount
        for model_class,field,start,team_cap,member_cap,label in windows:
            for scope,cap in [('team',team_cap),('user:'+str(user.pk),member_cap)]:
                bucket=model_class.objects.get_or_create(scope=scope,**{field:start})[0]
                available=max(Decimal('0'),cap-max(Decimal('0'),bucket.spent-bucket.reset_credit)-bucket.reserved) if cap is not None else amount
                if scope=='team' and available<amount:
                    raise ValidationError('团队'+label+'剩余额度不足（待核对费用也占用额度）。')
                if scope!='team': basic_available=min(basic_available,available)
                buckets.append((model_class,bucket,scope))
        extra=max(Decimal('0'),amount-basic_available)
        if extra>max(Decimal('0'),member.extra_balance-member.extra_reserved):
            raise ValidationError('你的剩余点数不足（包括额外点数；待核对费用也占用点数）。')
        if extra: Allowance.objects.filter(pk=member.pk).update(extra_reserved=F('extra_reserved')+extra)
        for model_class,bucket,scope in buckets:
            model_class.objects.filter(pk=bucket.pk).update(reserved=F('reserved')+(amount if scope=='team' else amount-extra))
        return Call.objects.create(user=user,model=model,price=price,purpose=purpose,group_id=group_id,
            project=project,experiment=experiment,reserved_cny=amount,extra_reserved_cny=extra,budget_month=month,budget_week=week)


def settle(call,counts,status='success',error_code='',cost_override=None):
    price=call.price; cost=None; cny=None
    if status=='failed': cost=Decimal('0'); cny=Decimal('0')
    if counts:
        uncached=counts['input_tokens']-counts['cached_tokens']-counts['cache_write_tokens']
        cost=(Decimal(uncached)*price.input_rate+Decimal(counts['cached_tokens'])*price.cached_rate+
            Decimal(counts['cache_write_tokens'])*price.cache_write_rate+Decimal(counts['output_tokens'])*price.output_rate)/1000000
        cost=cost.quantize(Q8); cny=(cost*price.cny_exchange_rate).quantize(Q8)
    elif cost_override is not None:
        cost=cost_override.quantize(Q8); cny=(cost*price.cny_exchange_rate).quantize(Q8)
    if status=='success' and cny is None: status='unknown'; error_code='usage_missing'
    with transaction.atomic():
        # Serialize settlements, grants and resets across WSGI workers.
        PoolSettings.objects.filter(pk=1).update(enabled=F('enabled'))
        if not Call.objects.filter(pk=call.pk,status__in=['running','unknown'],reconciled=False).exists(): return
        own_basic_reserved=call.reserved_cny-call.extra_reserved_cny
        basic_available=cny or Decimal('0')
        config=pool_settings(); member=Allowance.objects.get(user_id=call.user_id)
        for model_class,field,start,cap in [(BudgetWeek,'week',call.budget_week,config.default_weekly_limit)]:
            if cap is None: continue
            bucket=model_class.objects.get(scope='user:'+str(call.user_id),**{field:start})
            free=max(Decimal('0'),cap-max(Decimal('0'),bucket.spent-bucket.reset_credit)-bucket.reserved+own_basic_reserved)
            # Honor the admitted reservation if a limit was reduced while calling.
            basic_available=min(basic_available,max(own_basic_reserved,free))
        extra_cost=max(Decimal('0'),(cny or Decimal('0'))-basic_available) if cny is not None else None
        changed=Call.objects.filter(pk=call.pk,status__in=['running','unknown'],reconciled=False).update(
            status=status,error_code=error_code[:60],finished_at=timezone.now(),cost=cost,cost_cny=cny,
            extra_cost_cny=extra_cost,
            **(counts or {}),reconciled=cost_override is not None)
        if not changed: return
        if status in ('success','failed'):
            Allowance.objects.filter(user_id=call.user_id).update(
                extra_reserved=F('extra_reserved')-call.extra_reserved_cny,extra_balance=F('extra_balance')-(extra_cost or Decimal('0')))
            for model_class,field,start in [(BudgetMonth,'month',call.budget_month),(BudgetWeek,'week',call.budget_week)]:
                model_class.objects.filter(scope='team',**{field:start}).update(
                    reserved=F('reserved')-call.reserved_cny,spent=F('spent')+(cny or Decimal('0')))
                model_class.objects.filter(scope='user:'+str(call.user_id),**{field:start}).update(
                    reserved=F('reserved')-(call.reserved_cny-call.extra_reserved_cny),
                    spent=F('spent')+(cny or Decimal('0'))-(extra_cost or Decimal('0')))


def execute(user,model,messages,tools=None,limit=None,options=None,purpose='api',group_id=None,project=None,experiment=None):
    tools=tools or []; limit=min(limit or model.max_output_tokens,model.max_output_tokens)
    call=reserve(user,model,messages,tools,limit,purpose,group_id,project,experiment); began=time.monotonic()
    try:
        result=invoke(model,provider_key(model.provider),messages,tools,limit,options)
    except TransportError as error:
        settle(call,None,'unknown' if error.uncertain else 'failed',error.code)
        raise ValidationError('上游调用未完成（'+error.code+'）。'+('费用待核对，暂保留预留额度。' if error.uncertain else '本次未计费。')) from None
    except Exception:
        settle(call,None,'unknown','unexpected_response')
        raise ValidationError('上游结果无法处理，费用待核对。') from None
    Call.objects.filter(pk=call.pk).update(latency_ms=int((time.monotonic()-began)*1000),provider_request_id=result['id'])
    settle(call,result['counts']); call.refresh_from_db()
    result.update(call_id=str(call.pk),cost_cny=str(call.cost_cny) if call.cost_cny is not None else None,
        currency=call.price.currency,cost=str(call.cost) if call.cost is not None else None,price_version=call.price_id,status=call.status)
    return result
