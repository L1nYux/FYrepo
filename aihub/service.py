from core.tenancy import team_users, required_team_id, required_workspace_id
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import time
import threading
from contextlib import contextmanager
from decimal import Decimal, ROUND_UP
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F, Q
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


def remove_keys(identifiers):
    """Erase closed personal accounts' stored keys without touching organization keys."""
    if not identifiers:return
    target=secret_path()
    with transaction.atomic():
        Provider.all_objects.filter(pk__in=identifiers).update(enabled=False)
        try:values=json.loads(target.read_text('utf-8'))
        except FileNotFoundError:return
        for identifier in identifiers:values.pop(str(identifier),None)
        fd,name=tempfile.mkstemp(prefix='.pool-key-',dir=target.parent)
        try:
            os.chmod(name,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as output:json.dump(values,output)
            os.replace(name,target)
            os.chmod(target,0o600)
        finally:
            if os.path.exists(name):os.unlink(name)


def provider_key(provider):
    if provider.workspace_id != required_workspace_id(): raise PermissionDenied('不能使用其他团队的接口连接。')
    if provider.key_env and not provider.team_id: return ''
    if provider.key_env and provider.team_id != 1 and not provider.key_env.startswith(f'WORKBENCH_TEAM_{provider.team_id}_'):
        return ''
    if provider.key_env: return os.environ.get(provider.key_env,'')
    try: return json.loads(secret_path().read_text('utf-8')).get(str(provider.pk),'')
    except (OSError,ValueError): return ''


def store_key(provider, value):
    if provider.workspace_id != required_workspace_id(): raise PermissionDenied('接口连接不属于当前团队。')
    if not value: return
    target=secret_path()
    # SQLite write lock also serializes key updates made by different WSGI workers.
    with transaction.atomic():
        Provider.objects.filter(pk=provider.pk).update(enabled=provider.enabled)
        from core.models import Workspace
        if not Workspace.objects.filter(pk=provider.workspace_id,active=True).exists():raise PermissionDenied('空间已关闭。')
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
    profile = getattr(user, 'member_profile', None)
    if profile and profile.must_change_password: raise PermissionDenied('请先登录工作台设置新密码。')
    return user


def pool_settings():
    from core.tenancy import personal_owner_id
    return PoolSettings.objects.get_or_create(defaults={'owner_id':personal_owner_id()})[0]


def allowance(user):
    existing=Allowance.objects.filter(user=user).first()
    if existing:return existing
    config=pool_settings()
    with transaction.atomic():
        # First-use catalog and account-menu requests may initialize together.
        # Take the writer lock before get_or_create validates related records.
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        config=PoolSettings.objects.get(pk=config.pk)
        return Allowance.objects.get_or_create(user=user,defaults={'monthly_limit':config.default_member_limit,'weekly_limit':config.default_weekly_limit})[0]


def reset_member_plans(actor=None):
    """Refresh all active members' base plan; keep supplemental balances and billing."""
    from django.contrib.auth import get_user_model
    selected_workspace = required_workspace_id()
    with transaction.atomic():
        PoolSettings.objects.filter(workspace_id=selected_workspace).update(enabled=F('enabled'))
        for user in team_users().filter(is_active=True):
            if perms.is_team_member(user): reset_budget('user:'+str(user.pk),'week',actor=actor,reason='统一重置成员本周额度')


def month_now(): return timezone.localdate().replace(day=1)


def week_now():
    today=timezone.localdate()
    return today-timedelta(days=today.weekday())


def summary(user):
    from .gifts import expire_gifts
    expire_gifts()
    config=pool_settings(); member=allowance(user); month=month_now(); week=week_now()
    def bucket(model, period, scope, limit):
        if limit is not None:
            limit = Decimal(str(limit))
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
    return {'member':bucket(BudgetMonth,'month','user:'+str(user.pk),config.default_member_limit),
        'team':bucket(BudgetMonth,'month','team',config.monthly_limit),
        'member_week':bucket(BudgetWeek,'week','user:'+str(user.pk),config.default_weekly_limit),
        'team_week':bucket(BudgetWeek,'week','team',config.weekly_limit),
        'enabled':config.enabled and member.enabled,'month':str(month),'week':str(week),
        'extra': {'balance_points':str(member.extra_balance * 100),
            'reserved_points':str(member.extra_reserved * 100),
            'remaining_points':str(max(Decimal('0'),member.extra_balance-member.extra_reserved) * 100)},
        'preferred_model':member.preferred_model_id,
        'next_week_at':reset_time(week+timedelta(days=7)),'next_month_at':reset_time(next_month)}


def reset_budget(scope, period='both', *, actor=None, reason='', card=None):
    if period not in ('week','month','both'): raise ValidationError('重置周期无效。')
    from core.tenancy import team_users
    from .models import QuotaReset
    if scope != 'team' and (not scope.startswith('user:') or not scope[5:].isascii() or not scope[5:].isdigit() or len(scope[5:])>18 or not team_users(member_only=True).filter(pk=scope[5:]).exists()):
        raise ValidationError('请选择本团队成员。')
    config=pool_settings()
    with transaction.atomic():
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        restored = Decimal('0')
        periods = {}
        for model,field,start in ((BudgetWeek,'week',week_now()),(BudgetMonth,'month',month_now())):
            if period not in (field,'both'): continue
            row=model.objects.get_or_create(scope=scope,**{field:start})[0]
            amount = max(Decimal('0'), row.spent-row.reset_credit)+row.reserved
            periods[field] = str(amount)
            restored = max(restored, amount)
            # A reset starts a fresh allowance generation. Old calls retain their
            # ledger and supplemental reservations, but cannot consume this generation.
            model.objects.filter(pk=row.pk).update(reset_credit=F('spent'),reserved=0,
                generation=F('generation')+1,reset_at=timezone.now())
        QuotaReset.objects.create(scope=scope,period=period,actor=actor,card=card,reason=reason[:200],restored_cny=restored,restored_periods=periods)


def create_token(user,label,experiment=None,project=None,*,expires_at=None,allowed_models=None,cost_limit_cny=None):
    require_member(user)
    from core.tenancy import team_id
    if team_id() is None:raise PermissionDenied('API Key 必须属于团队。')
    project,experiment=independent_context(user,experiment.pk if experiment else None,project.pk if project else None)
    token='fy_'+secrets.token_urlsafe(32)
    with transaction.atomic():
        config=pool_settings()
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        if config.max_active_keys and MemberToken.objects.filter(user=user,revoked_at__isnull=True).filter(Q(expires_at__isnull=True)|Q(expires_at__gt=timezone.now())).count()>=config.max_active_keys:
            raise ValidationError(f'最多保留 {config.max_active_keys} 个有效 API Key，请先撤销不用的 Key，或联系管理员调整上限。')
        MemberToken.objects.create(user=user,label=label[:80] or '我的 API Key',prefix=token[:12],digest=hashlib.sha256(token.encode()).hexdigest(),
            experiment=experiment,experiment_bound=experiment is not None,expires_at=expires_at,
            allowed_models=allowed_models or [],cost_limit_cny=cost_limit_cny,
            project=project if experiment is None else None,project_bound=project is not None and experiment is None)
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


def callable_experiments(user):
    """Optional experiment attribution is limited to accessible working records."""
    require_member(user)
    records=Experiment.objects.select_related('project').filter(project__archived_at__isnull=True).exclude(status='archived')
    if not perms.is_admin(user):
        records=records.filter(Q(created_by=user)|Q(project__owner=user)|Q(project__members=user)).distinct()
    return records


def callable_projects(user):
    require_member(user)
    records=Project.objects.filter(archived_at__isnull=True)
    if not perms.is_admin(user):
        records=records.filter(Q(owner=user)|Q(members=user)).distinct()
    return records


def independent_context(user,experiment_id,project_id=None):
    require_member(user)
    experiment=None;project=None
    if experiment_id is not None:
        if type(experiment_id) is not int or not 0<experiment_id<=9223372036854775807:
            raise ValidationError('experiment_id 必须是正整数。')
        experiment=callable_experiments(user).filter(pk=experiment_id).first()
        if not experiment:raise ValidationError('关联实验不存在、已归档或你没有调用权限。')
    if project_id is not None:
        if type(project_id) is not int or not 0<project_id<=9223372036854775807:
            raise ValidationError('project_id 必须是正整数。')
        if experiment and project_id!=experiment.project_id:
            raise ValidationError('实验与项目不一致。')
        project=experiment.project if experiment else callable_projects(user).filter(pk=project_id).first()
        if not project:raise ValidationError('关联项目不存在、已归档或你没有调用权限。')
    return project or (experiment.project if experiment else None),experiment


def reserve(user,model,messages,tools,limit,purpose,group_id,project,experiment,*,api_token=None):
    from core.tenancy import team_id
    if team_id() is None:raise PermissionDenied('付费调用必须使用获授权团队的 API 池。')
    from .gifts import expire_gifts
    expire_gifts()
    require_member(user); config=pool_settings(); member=allowance(user)
    if not config.enabled or not member.enabled: raise ValidationError('API 池或你的调用权限已暂停。')
    if not model.enabled or not model.provider.enabled: raise ValidationError('该厂商或模型已停用。')
    if not provider_key(model.provider): raise ValidationError('管理员尚未配置该厂商的密钥。')
    price=current_price(model)
    if not price: raise ValidationError('该模型尚未登记有效价格。')
    from .token_estimates import input_estimate
    estimate=input_estimate(model,messages,tools)
    size=estimate['bytes']
    from django.conf import settings
    ceiling=settings.WORKBENCH_RELAY_MAX_CONTEXT_BYTES
    if size>ceiling:
        from .relay import RelayError
        raise RelayError(f'消息和工具上下文超过中转上限 {ceiling} 字节。', 'context_too_large', 413,
                         details={'max_bytes':ceiling,'received_bytes':size})
    image_values=[value for row in messages for value in row.get('_images',[])]
    if any(not isinstance(value,str) or not value.startswith('data:image/jpeg;base64,') for value in image_values):raise ValidationError('图片内容无效，请重新上传。')
    if len(image_values)>8 or sum(len(value) for value in image_values)>12*1024*1024:raise ValidationError('图片上下文过长，请开始新对话。')
    if image_values:
        from .images import supports_images
        if not supports_images(model):raise ValidationError('当前模型无法读取图片，请切换支持识图的模型；本次未发起调用、不扣点数。')
    # Images are normalized to <=1536 px. Base64 bytes are not text tokens;
    # reserve a conservative image allowance and settle actual provider usage.
    input_ceiling=estimate['tokens']
    from .prices import rates_for_tokens
    rates=rates_for_tokens(price,input_ceiling)
    amount=((Decimal(input_ceiling)*max(rates['input_rate'],rates['cached_rate'],rates['cache_write_rate'])+Decimal(limit)*rates['output_rate'])/1000000*price.cny_exchange_rate).quantize(Q8,rounding=ROUND_UP)
    if amount>config.max_call_cost:
        from .relay import RelayError
        raise RelayError('本次预计预留超过团队单次上限，请降低 max_tokens 或由管理员调整单次上限。',
            'reservation_limit_exceeded',429,details={'estimated_cny':str(amount),'max_call_cny':str(config.max_call_cost),
                'estimated_input_tokens':input_ceiling,'max_output_tokens':limit,'estimate_method':estimate['method']})
    month=month_now(); week=week_now()
    with transaction.atomic():
        # Take the writer lock before reads inside the transaction, avoiding SQLite read-to-write races.
        from core.models import Team
        Team.objects.filter(pk=team_id()).update(active=F('active'))
        if not Team.objects.filter(pk=team_id(),active=True).exists():raise PermissionDenied('团队已解散，未发起调用。')
        require_member(user)
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        config.refresh_from_db(); member.refresh_from_db()
        if not config.enabled or not member.enabled: raise ValidationError('API 池或你的调用权限已暂停。')
        if not PoolModel.objects.filter(pk=model.pk, enabled=True, provider__enabled=True,
                provider_id=model.provider_id, model_id=model.model_id).exists():
            raise ValidationError('模型或调用连接已变化，请重新选择。')
        if api_token is not None:
            from .relay import check_token, RelayError
            locked=MemberToken.objects.select_for_update().filter(pk=api_token.pk,user=user).first()
            if not locked: raise RelayError('API Key 无效。','invalid_api_key',401)
            check_token(locked,model,amount)
            MemberToken.objects.filter(pk=locked.pk).update(last_used_at=timezone.now())
        windows=[(BudgetMonth,'month',month,config.monthly_limit,config.default_member_limit,'本月'),
                 (BudgetWeek,'week',week,config.weekly_limit,config.default_weekly_limit,'本周')]
        buckets=[]; basic_available=amount; generations={}
        for model_class,field,start,team_cap,member_cap,label in windows:
            for scope,cap in [('team',team_cap),('user:'+str(user.pk),member_cap)]:
                bucket=model_class.objects.get_or_create(scope=scope,**{field:start})[0]
                generations[('team_' if scope=='team' else 'member_')+field]=bucket.generation
                if model_class is BudgetWeek and not bucket.base_limit_recorded:
                    BudgetWeek.objects.filter(pk=bucket.pk,base_limit_recorded=False).update(base_limit_snapshot=cap,base_limit_recorded=True)
                available=max(Decimal('0'),cap-max(Decimal('0'),bucket.spent-bucket.reset_credit)-bucket.reserved) if cap is not None else amount
                if scope=='team' and available<amount:
                    from .relay import RelayError
                    raise RelayError('团队'+label+'剩余额度不足（待核对费用也占用额度）。','insufficient_quota',429)
                if scope!='team': basic_available=min(basic_available,available)
                buckets.append((model_class,bucket,scope))
        extra=max(Decimal('0'),amount-basic_available)
        if extra>max(Decimal('0'),member.extra_balance-member.extra_reserved):
            from .relay import RelayError
            raise RelayError('你的剩余点数不足（包括额外点数；待核对费用也占用点数）。','insufficient_quota',429)
        if extra: Allowance.objects.filter(pk=member.pk).update(extra_reserved=F('extra_reserved')+extra)
        for model_class,bucket,scope in buckets:
            model_class.objects.filter(pk=bucket.pk).update(reserved=F('reserved')+(amount if scope=='team' else amount-extra))
        return Call.objects.create(user=user,model=model,price=price,purpose=purpose,group_id=group_id,api_token=api_token,
            project=project,experiment=experiment,reserved_cny=amount,extra_reserved_cny=extra,budget_month=month,budget_week=week,
            quota_generations=generations,request_bytes=size,estimated_input_tokens=input_ceiling,estimate_method=estimate['method'],
            upstream_model=model.model_id,provider_endpoint=model.provider.base_url,provider_name=model.provider.name,
            public_model=model.public_alias or str(model.provider_id)+'/'+model.model_id)


def settle(call,counts,status='success',error_code='',cost_override=None):
    price=call.price; cost=None; cny=None
    if status=='failed': cost=Decimal('0'); cny=Decimal('0')
    if counts:
        from .prices import rates_for_tokens
        rates=rates_for_tokens(price,counts['input_tokens'])
        uncached=counts['input_tokens']-counts['cached_tokens']-counts['cache_write_tokens']
        cost=(Decimal(uncached)*rates['input_rate']+Decimal(counts['cached_tokens'])*rates['cached_rate']+
            Decimal(counts['cache_write_tokens'])*rates['cache_write_rate']+Decimal(counts['output_tokens'])*rates['output_rate'])/1000000
        cost=cost.quantize(Q8); cny=(cost*price.cny_exchange_rate).quantize(Q8)
    elif cost_override is not None:
        cost=cost_override.quantize(Q8); cny=(cost*price.cny_exchange_rate).quantize(Q8)
    if status=='success' and cny is None: status='unknown'; error_code='usage_missing'
    selected_workspace = required_workspace_id()
    with transaction.atomic():
        # Serialize settlements, grants and resets across WSGI workers.
        PoolSettings.objects.filter(workspace_id=selected_workspace).update(enabled=F('enabled'))
        if not Call.objects.filter(pk=call.pk,status__in=['running','unknown'],reconciled=False).exists(): return
        own_basic_reserved=call.reserved_cny-call.extra_reserved_cny
        basic_available=cny or Decimal('0')
        config=pool_settings(); member=Allowance.objects.get(user_id=call.user_id)
        def current_generation(bucket, kind, field):
            # Pre-upgrade calls and windows both belong to generation zero.
            return bucket.generation == call.quota_generations.get(kind+'_'+field,0)
        for model_class,field,start,cap in [(BudgetWeek,'week',call.budget_week,config.default_weekly_limit), (BudgetMonth,'month',call.budget_month,config.default_member_limit)]:
            bucket=model_class.objects.get(scope='user:'+str(call.user_id),**{field:start})
            if not current_generation(bucket,'member',field):
                basic_available=min(basic_available,own_basic_reserved)
                continue
            if cap is None: continue
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
                for kind,scope,held,charged in [('team','team',call.reserved_cny,cny or Decimal('0')),
                    ('member','user:'+str(call.user_id),own_basic_reserved,(cny or Decimal('0'))-(extra_cost or Decimal('0')))]:
                    bucket=model_class.objects.get(scope=scope,**{field:start})
                    change={'spent':F('spent')+charged}
                    if current_generation(bucket,kind,field): change['reserved']=F('reserved')-held
                    else: change['reset_credit']=F('reset_credit')+charged
                    model_class.objects.filter(pk=bucket.pk).update(**change)


@contextmanager
def keep_call_alive(call):
    """Only live workers refresh this marker; a restarted worker cannot revive a call."""
    from django.db import close_old_connections, connections, OperationalError
    from core.tenancy import scope
    stopped=threading.Event(); workspace=call.workspace
    def heartbeat():
        try:
            with scope(workspace):
                while not stopped.wait(30):
                    close_old_connections()
                    try:
                        with transaction.atomic():
                            Call.objects.filter(pk=call.pk,status='running').update(heartbeat_at=timezone.now())
                    except OperationalError: pass
        finally: connections.close_all()
    worker=threading.Thread(target=heartbeat,name='api-call-heartbeat',daemon=True);worker.start()
    try: yield
    finally: stopped.set();worker.join(timeout=2)


def execute(user,model,messages,tools=None,limit=None,options=None,purpose='api',group_id=None,project=None,experiment=None,on_progress=None,on_reserved=None,api_token=None):
    tools=tools or []; limit=min(limit or model.max_output_tokens,model.max_output_tokens)
    call=reserve(user,model,messages,tools,limit,purpose,group_id,project,experiment,api_token=api_token); began=time.monotonic()
    if on_reserved is not None:
        try:on_reserved(call)
        except Exception:
            # The request has not left this process; release its reservation.
            settle(call,None,'failed','execution_checkpoint_failed')
            raise
    emitted=False
    def report_progress(value):
        nonlocal emitted
        if value.get('text') or value.get('reasoning') or value.get('tool_calls'):
            emitted=True
            if call.first_token_ms is None:
                call.first_token_ms=int((time.monotonic()-began)*1000)
                Call.objects.filter(pk=call.pk,first_token_ms__isnull=True).update(first_token_ms=call.first_token_ms)
        return on_progress(value)
    try:
        with keep_call_alive(call):
            if on_progress is None:
                result=invoke(model,provider_key(model.provider),messages,tools,limit,options)
            else:
                result=invoke(model,provider_key(model.provider),messages,tools,limit,options,on_progress=report_progress)
    except TransportError as error:
        Call.objects.filter(pk=call.pk).update(latency_ms=int((time.monotonic()-began)*1000))
        uncertain=error.uncertain or emitted
        settle(call,None,'unknown' if uncertain else 'failed',error.code)
        detail = ''
        if error.diagnostic:
            detail = ' 参数诊断：'+json.dumps(error.diagnostic,ensure_ascii=False,separators=(',',':'))+'。'
            logging.getLogger('aihub.inference').warning('Rejected inference call=%s model=%s code=%s validation=%s',
                call.pk,model.pk,error.code,json.dumps(error.diagnostic,ensure_ascii=False))
        from .relay import RelayError
        raise RelayError('上游调用未完成（'+error.code+'）。'+('费用待核对，暂保留预留额度。' if uncertain else '本次未计费。')
            +' 调用编号：'+str(call.pk)+'。'+detail,'upstream_result_unknown' if uncertain else 'upstream_error',502,call_id=str(call.pk)) from None
    except Exception:
        settle(call,None,'unknown','unexpected_response')
        from .relay import RelayError
        raise RelayError('上游结果无法处理，费用待核对。','upstream_result_unknown',502,call_id=str(call.pk)) from None
    Call.objects.filter(pk=call.pk).update(latency_ms=int((time.monotonic()-began)*1000),provider_request_id=result['id'])
    settle(call,result['counts']); call.refresh_from_db()
    result.update(call_id=str(call.pk),cost_cny=str(call.cost_cny) if call.cost_cny is not None else None,
        currency=call.price.currency,cost=str(call.cost) if call.cost is not None else None,price_version=call.price_id,status=call.status)
    return result
