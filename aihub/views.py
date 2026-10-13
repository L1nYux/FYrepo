from core.tenancy import team_users, required_team_id, required_workspace_id
from .presentation import display_result, clean_response
import hashlib
import json
import math
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlencode
from django.contrib import messages as notices
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core import signing
from django.core.paginator import Paginator
from django.db import transaction, OperationalError
from django.db.models import Sum, Count, F, Q, Exists, OuterRef
from django.http import JsonResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.cache import never_cache
from core import permissions as perms
from core.models import Project, Experiment
from . import agent
from . import discovery
from .permissions import is_pool_owner,require_pool_owner,visible_budget
from .models import Provider, PoolModel, DailyPrice, PriceVersion, MemberToken, Call, AssistantJob, AssistantConversation, Allowance, PointGrant, AssistantImage, ResetCard, QuotaReset
from . import images as image_inputs
from .forms import ProviderForm, ModelForm, SimplePriceForm, SettingsForm, PlanForm, PointGrantForm, CallLimitsForm
from .automatic_prices import enrich_catalog, automatic_price, AUTO
from .prices import current_price, save_price, refresh_prices
from .service import provider_key, store_key, require_member, summary, pool_settings, allowance, create_token, execute, settle, reset_budget, grant_points, reset_member_plans
from .service import callable_experiments, callable_projects, independent_context


def issue_points(request):
    require_pool_owner(request)
    form = PointGrantForm(request.POST)
    if not form.is_valid(): raise ValidationError('请输入有效的额外点数，或刷新页面后重新发放。')
    all_members=request.POST.get('user')=='all'
    users=[u for u in team_users().filter(is_active=True).order_by('pk') if perms.is_team_member(u)] if all_members else [get_object_or_404(team_users(), pk=int(request.POST.get('user')))]
    added=0
    with transaction.atomic():
        config=pool_settings(); type(config).objects.filter(pk=config.pk).update(enabled=F('enabled'))
        for user in users:
            grant_id=uuid.uuid5(form.cleaned_data['grant_id'],f'{required_workspace_id()}:{user.pk}')
            added+=int(grant_points(user,request.user,form.cleaned_data['points'],grant_id))
    notices.success(request, f'已为 {added} 位成员发放额外点数，跨周保留。' if added else '这笔点数已经发放，无需重复操作。')


def save_plan(request):
    require_pool_owner(request)
    form=PlanForm(request.POST)
    if not form.is_valid(): raise ValidationError('请输入有效的每周点数（整数，0 表示暂停基础额度）。')
    config=pool_settings()
    with transaction.atomic():
        type(config).objects.filter(pk=config.pk).update(default_weekly_limit=form.cleaned_data['points']/100)
    notices.success(request,'统一每周额度已保存，对所有现有成员和新成员立即生效；本周已用点数保留。')


def team(view):
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        if not request.user.is_authenticated:
            if wrapper.expects_json or request.headers.get('Authorization', '').startswith('Bearer '):
                return JsonResponse({'error':'登录已失效，请重新登录。'}, status=401)
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        try:
            private_views=('assistant','assistant_start','assistant_upload_image','assistant_image','assistant_conversations','assistant_conversation','assistant_job','assistant_capabilities','references')
            if view.__name__ not in private_views and getattr(request.workspace,'kind',None)!='team':
                if not wrapper.expects_json:return render(request,'aihub/team_required.html')
                return JsonResponse({'error':'请先选择或加入团队，再使用团队 API 池。'},status=403)
            require_member(request.user)
        except PermissionDenied:
            if wrapper.expects_json:
                return JsonResponse({'error':'当前账户无权执行。'}, status=403)
            raise
        return view(request,*args,**kwargs)
    wrapper.expects_json = view.__name__ not in ('pool', 'assistant', 'manage')
    return wrapper


def json_errors(view):
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        try: return view(request,*args,**kwargs)
        except ValidationError as error:
            if view.__name__.startswith('api_'):
                return relay_error(' '.join(error.messages),getattr(error,'http_status',400),getattr(error,'api_code','invalid_request'),getattr(error,'call_id',None),getattr(error,'details',None))
            return JsonResponse({'error':' '.join(error.messages)},status=400)
        except PermissionDenied:
            if view.__name__.startswith('api_'):return relay_error('当前账户无权执行。',403,'permission_denied')
            return JsonResponse({'error':'当前账户无权执行。'},status=403)
        except (ValueError,TypeError,KeyError,InvalidOperation):
            if view.__name__.startswith('api_'):return relay_error('参数无效。')
            return JsonResponse({'error':'参数无效。'},status=400)
    return wrapper


def json_body(request):
    if len(request.body)>220000: raise ValidationError('请求过长。')
    data=json.loads(request.body)
    if not isinstance(data,dict): raise ValidationError('请求格式无效。')
    return data


def relay_error(message, status=400, code='invalid_request', call_id=None, details=None):
    value={'error':{'message':message,'type':'authentication_error' if status==401 else 'permission_error' if status==403 else 'rate_limit_error' if status==429 else 'server_error' if status>=500 else 'invalid_request_error','param':None,'code':code}}
    if call_id: value['error']['call_id']=call_id
    if details:value['error']['limits']=details
    response=JsonResponse(value,status=status)
    if call_id: response['X-Request-ID']=call_id
    # An SDK retry must never repeat a request that may already have been billed.
    response['x-should-retry']='false'
    if details and 'max_bytes' in details:response['X-Request-Body-Limit']=str(details['max_bytes'])
    return response


def relay_errors(view):
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        from .relay import RelayError
        try: return view(request,*args,**kwargs)
        except RelayError as error: return relay_error(' '.join(error.messages),error.http_status,error.api_code,error.call_id,error.details)
        except ValidationError as error: return relay_error(' '.join(error.messages))
        except PermissionDenied: return relay_error('当前账户无权执行。',403,'permission_denied')
        except Http404: return relay_error('记录不存在或不可访问。',404,'not_found')
        except (ValueError,TypeError,KeyError,InvalidOperation,RecursionError): return relay_error('参数无效。')
    return wrapper


def model_catalog(user):
    require_member(user); result=[]; owner=is_pool_owner(user)
    for model in PoolModel.objects.filter(enabled=True,provider__enabled=True).select_related('provider'):
        price=current_price(model); daily=model.daily_prices.order_by('-day').first()
        result.append({'id':model.pk,'provider_id':model.provider_id,'provider':model.provider.name,'model_id':model.model_id,
            'alias':model.public_alias or str(model.provider_id)+'/'+model.model_id,'label':discovery.model_label(model.model_id,str(model)),'supports_tools':model.supports_tools,
            'supports_images':image_inputs.supports_images(model),
            'supports_thinking_toggle':__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(model.provider.base_url).hostname=='api.deepseek.com',
            'configured':bool(provider_key(model.provider)) and price is not None,
            'max_output_tokens':model.max_output_tokens,'default_output_tokens':min(model.default_output_tokens,model.max_output_tokens),'protocol':model.provider.protocol,
            'input_rate':str(price.input_rate) if price else None,'output_rate':str(price.output_rate) if price else None,
            'currency':price.currency if price else '', 'price_status':daily.get_status_display() if daily else '尚无每日记录',
            'price_day':str(daily.day) if daily else None})
        if not owner:
            for name in ('input_rate','output_rate','currency','price_status','price_day'): result[-1].pop(name,None)
    return result


def pool_destination(name='api_pool', scope=None):
    """Carry the authorized workspace through management redirects."""
    query={'ownership':required_workspace_id()}
    if scope:query['scope']=scope
    return reverse(name)+'?'+urlencode(query)


@team
@never_cache
def pool(request):
    fresh_token=''
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='new_token':
            try:
                def optional_id(name):
                    value=request.POST.get(name,'')
                    if not value:return None
                    if not value.isascii() or not value.isdecimal() or len(value)>18:raise ValidationError('请选择有效的项目或实验。')
                    return int(value)
                project,experiment=independent_context(request.user,optional_id('experiment_id'),optional_id('project_id'))
                from .relay import key_options
                fresh_token=create_token(request.user,request.POST.get('label','我的 API Key'),experiment,project,**key_options(request.POST))
            except ValidationError as error: notices.error(request,' '.join(error.messages))
        elif action=='revoke_token':
            MemberToken.objects.filter(pk=request.POST.get('id'),user=request.user).update(revoked_at=timezone.now())
            return redirect(pool_destination())
        elif action in ('issue_reset_cards','use_reset_card','revoke_reset_card'):
            from . import quota_cards
            try:
                if action=='use_reset_card':
                    changed=quota_cards.redeem(request.user,request.POST.get('id'))
                    notices.success(request,'周期基础额度已恢复；旧调用仍记账，不占用恢复后的基础额度。' if changed else '这张重置卡已经使用。')
                elif action=='issue_reset_cards':
                    require_pool_owner(request)
                    count=quota_cards.issue(request.user,request.POST.get('user'),request.POST.get('period','week'),request.POST.get('count','1'),request.POST.get('days','30'),request.POST.get('batch_id'))
                    notices.success(request,f'已发放 {count} 张重置卡。' if count else '这批重置卡已经发放。')
                else:
                    require_pool_owner(request);quota_cards.revoke(request.user,request.POST.get('id'));notices.success(request,'未使用的重置卡已撤销。')
            except ValidationError as error: notices.error(request,' '.join(error.messages))
            return redirect(pool_destination(scope='team' if action!='use_reset_card' else None))
        elif action=='reset_budget':
            require_pool_owner(request)
            try:
                scope='team' if request.POST.get('target')=='team' else 'user:'+str(get_object_or_404(User,pk=int(request.POST.get('user'))).pk)
                reset_budget(scope,request.POST.get('period','both'),actor=request.user,reason=request.POST.get('reason','管理员恢复额度'))
            except (ValidationError,ValueError,TypeError,OverflowError) as error:
                notices.error(request,' '.join(error.messages) if isinstance(error,ValidationError) else '请选择有效成员。')
            else:
                notices.success(request,'基础额度已重置；旧调用仍记账，不占用恢复后的基础额度。')
            return redirect(pool_destination(scope='team'))
        elif action=='grant_points':
            require_pool_owner(request)
            try: issue_points(request)
            except (ValidationError, ValueError, TypeError, OverflowError) as error:
                notices.error(request,' '.join(error.messages) if isinstance(error,ValidationError) else '请选择有效成员。')
            return redirect(pool_destination(scope='team'))
        elif action=='save_plan':
            require_pool_owner(request)
            try: save_plan(request)
            except ValidationError as error: notices.error(request,' '.join(error.messages))
            return redirect(pool_destination(scope='team'))
        elif action=='reset_plans':
            require_pool_owner(request)
            reset_member_plans(request.user); notices.success(request,'所有成员的本周基础额度已重置，额外点数和历史费用保留。')
            return redirect(pool_destination(scope='team'))
        elif action=='settings':
            require_pool_owner(request)
            form=SettingsForm(request.POST,instance=pool_settings())
            if form.is_valid(): form.save(); notices.success(request,'额度已保存。')
            else: notices.error(request,' '.join(str(e) for errors in form.errors.values() for e in errors))
            return redirect(pool_destination(scope='team'))
        elif action=='call_limits':
            require_pool_owner(request)
            form=CallLimitsForm(request.POST,instance=pool_settings())
            if form.is_valid():
                form.save();notices.success(request,'调用限制已保存。')
            else:notices.error(request,'请输入有效的调用限制，0 表示不额外限制。')
            return redirect(pool_destination(scope='team'))
    calls=Call.objects.select_related('user','model__provider','price','project','experiment')
    scope=request.GET.get('scope','mine')
    if scope!='team' or not is_pool_owner(request): calls=calls.filter(user=request.user); scope='mine'
    provider=request.GET.get('provider',''); model=request.GET.get('model',''); month=request.GET.get('month','')
    if provider.isdigit(): calls=calls.filter(model__provider_id=provider)
    if model.isdigit(): calls=calls.filter(model_id=model)
    try:
        if month:
            year,part=map(int,month.split('-')); calls=calls.filter(created_at__year=year,created_at__month=part)
    except (ValueError,TypeError): month=''
    totals=calls.aggregate(count=Count('pk'),input=Sum('input_tokens'),output=Sum('output_tokens'),cost=Sum('cost_cny'))
    by_member=list(calls.values('user__username').annotate(count=Count('pk'),input=Sum('input_tokens'),output=Sum('output_tokens'),cost=Sum('cost_cny')).order_by('user__username')) if scope=='team' else []
    page=Paginator(calls,30).get_page(request.GET.get('page'))
    catalog=model_catalog(request.user)
    from .relay import token_usage
    tokens=list(MemberToken.objects.filter(user=request.user).select_related('experiment','project').order_by('-pk')[:100])
    for item in tokens: item.relay_usage=token_usage(item)
    from .usage import dashboard
    return render(request,'aihub/pool.html',{'budget':visible_budget(request.user),'catalog':catalog,'page':page,'totals':totals,
        'usage':dashboard(request.user,scope=='team'),'pool_settings':pool_settings() if is_pool_owner(request) else None,'batch_grant_id':str(uuid.uuid4()),
        'point_grants':(PointGrant.objects.all() if scope=='team' else PointGrant.objects.filter(user=request.user)).select_related('user','issued_by').order_by('-created_at', '-pk')[:30],
        'tokens':tokens,'fresh_token':fresh_token,'scope':scope,
        'reset_cards':(ResetCard.objects.all() if scope=='team' else ResetCard.objects.filter(user=request.user)).select_related('user','issued_by')[:200],
        'reset_card_batch':str(uuid.uuid4()), 'now':timezone.now(),'quota_resets':QuotaReset.objects.select_related('actor','card')[:30] if scope=='team' else QuotaReset.objects.filter(scope='user:'+str(request.user.pk))[:10],
        'personal_api_url':request.build_absolute_uri('/v1'),
        'personal_api_root':request.build_absolute_uri('/').rstrip('/'),
        'personal_api_experiments':callable_experiments(request.user) if scope=='mine' else [],
        'personal_api_projects':callable_projects(request.user) if scope=='mine' else [],
        'personal_api_selected_project':request.POST.get('project_id','') if scope=='mine' else '',
        'personal_api_selected_experiment':request.POST.get('experiment_id','') if scope=='mine' else '',
        'providers':Provider.objects.filter(Q(enabled=True)|Q(models__isnull=False)).distinct() if is_pool_owner(request) else [],'selected_provider':provider,'selected_model':model,'selected_month':month,
        'by_member':by_member,'price_history':PriceVersion.objects.select_related('model__provider').all()[:50] if is_pool_owner(request) else [],
        'daily':DailyPrice.objects.select_related('model__provider','price').order_by('-day','model_id')[:50] if is_pool_owner(request) else []})


@team
def assistant(request):
    from .funding import choices
    teams=choices(request.user)
    if not teams:return render(request,'aihub/team_required.html')
    preferred=next((s for s in teams if s.team_id==request.session.get('workbench-team')),None)
    return render(request,'aihub/assistant.html',{'context_kind':request.GET.get('kind',''),'context_id':request.GET.get('id',''),'funding_choices':teams,'selected_funding':preferred or teams[0]})


@team
@require_POST
@json_errors
def discover_models(request):
    require_pool_owner(request)
    data=json_body(request); values=discovery.connection(data); key=discovery.clean_key(data.get('api_key',''))
    existing=get_object_or_404(Provider,pk=int(data['id'])) if data.get('id') else Provider.objects.filter(base_url=values['base_url'],protocol=values['protocol']).annotate(model_count=Count('models')).order_by('-model_count','-pk').first()
    if existing and (existing.base_url.rstrip('/')!=values['base_url'] or existing.protocol!=values['protocol']) and not key:
        raise ValidationError('更换接口地址或格式时需要重新填写 Key。')
    from types import SimpleNamespace
    resolved_key=key or (provider_key(existing) if existing else '')
    rows,truncated=discovery.fetch_models(SimpleNamespace(**values),resolved_key)
    price_note,fx=enrich_catalog(SimpleNamespace(**values),rows,key=resolved_key)
    # Discovery is a proposal, not a mutation of a working provider or key.
    item=existing
    saved={m.model_id:m for m in item.models.all()} if item else {}
    for row in rows:
        model=saved.get(row['id']); price=current_price(model) if model else None
        row['selected']=bool(model and model.enabled)
        row['has_price']=price is not None
        row['saved_currency']=price.currency if price else ''
    from .pending_discovery import stage
    ticket=signing.dumps({'proposal':stage({'user':request.user.pk,'provider':item.pk if item else None,'values':values,'key':key,'rows':rows})},salt='api-discovery')
    from .model_catalog import channel
    return JsonResponse({'provider':item.pk if item else '', 'models':rows,'ticket':ticket,'truncated':truncated,'price_note':price_note,'exchange':fx,'channel':channel(SimpleNamespace(**values))})


@team
@require_POST
@json_errors
def enable_models(request):
    require_pool_owner(request)
    data=json_body(request)
    from .pending_discovery import load, discard
    try:
        proposal = signing.loads(str(data.get('ticket','')),salt='api-discovery',max_age=900)['proposal']
        catalog=load(proposal, request.user)
    except signing.BadSignature: raise ValidationError('模型列表已过期，请重新读取。') from None
    if catalog['user']!=request.user.pk: raise PermissionDenied
    selected=data.get('models',[])
    if not isinstance(selected,list) or not selected or any(not isinstance(v,str) for v in selected): raise ValidationError('请至少选择一个模型。')
    available={r['id']:r for r in catalog['rows']}
    if set(selected)-available.keys(): raise ValidationError('选择的模型不在本次读取列表中。')
    from .model_catalog import describe
    if any(available[identifier].get('assistant_supported',describe(identifier)['assistant_supported']) is False for identifier in selected):
        raise ValidationError('所选模型包含当前助手暂不支持的用途，请选择对话模型。')
    missing=[]; config=pool_settings()
    with transaction.atomic():
        type(config).objects.filter(pk=config.pk).update(enabled=F('enabled'))
        provider=get_object_or_404(Provider,pk=catalog['provider']) if catalog['provider'] else Provider()
        for name,value in catalog['values'].items():
            if name != 'name' or not provider.pk: setattr(provider,name,value)
        if catalog['key']: provider.key_env=''
        provider.enabled=True; provider.full_clean(); provider.save()
        for identifier in set(selected):
            row=available[identifier]
            model,created=PoolModel.objects.get_or_create(provider=provider,model_id=identifier,defaults={
                'label':row['label'],'supports_tools':row['supports_tools'],'supports_images':row.get('supports_images'),'max_output_tokens':row['max_output_tokens'],'output_parameter':row['output_parameter']})
            model.enabled=True; model.save(update_fields=['enabled'])
            price=current_price(model)
            if model.price_mode=='auto' and row.get('price'):
                proposed=row['price']; fx=proposed.get('cny_exchange_rate') or data.get('exchange_rate')
                if proposed['currency']=='CNY' or fx:
                    save_price(model,{**proposed,'cny_exchange_rate':1 if proposed['currency']=='CNY' else fx},proposed['source'])
                    price=current_price(model)
            if price is None: missing.append({'id':model.pk,'label':str(model)})
        # Only the list just fetched is affected; unlisted existing models keep their settings.
        provider.models.filter(model_id__in=available.keys()).exclude(model_id__in=selected).update(enabled=False)
        store_key(provider,catalog['key'])
        from .routing import reset_health
        reset_health(provider)
    discard(proposal)
    return JsonResponse({'saved':True,'missing_prices':missing})


@team
@require_POST
@json_errors
def update_model_price(request):
    require_pool_owner(request)
    data=json_body(request); model=get_object_or_404(PoolModel,pk=data.get('id'))
    if data.get('action')=='automatic':
        from .vendor_prices import source_info, PriceUnavailable
        info=source_info(model.provider)
        if not info['supported']: raise ValidationError(info['note'])
        try: proposed=automatic_price(model.provider,model.model_id,force=True)
        except PriceUnavailable as exc: raise ValidationError(str(exc)) from None
        except Exception: raise ValidationError('自动读取暂时失败，已有价格已保留；请稍后重试。') from None
        if not proposed: raise ValidationError('已读取官方价格来源，但未找到这个模型的可用单价；请核对模型 ID 或手动登记，已有价格保留。')
        save_price(model,proposed,proposed['source'])
        PoolModel.objects.filter(pk=model.pk).update(price_mode='auto')
    else:
        form=SimplePriceForm(data)
        if not form.is_valid(): raise ValidationError(' '.join(str(e) for errors in form.errors.values() for e in errors))
        save_price(model,form.cleaned_data,'管理员登记')
        PoolModel.objects.filter(pk=model.pk).update(price_mode='manual')
    price=current_price(model)
    DailyPrice.objects.update_or_create(model=model,day=timezone.localdate(),defaults={
        'price':price,'status':'verified' if data.get('action')=='automatic' else 'manual','note':price.source[:300]})
    return JsonResponse({'saved':True,'input_rate':str(price.input_rate),'output_rate':str(price.output_rate),'currency':price.currency,'source':price.source})


@team
@require_GET
@json_errors
def catalog(request):
    if request.GET.get('funding'):
        from .funding import resolve,catalog as funded_catalog
        return JsonResponse(funded_catalog(request.user,resolve(request.user,request.GET['funding'])))
    return JsonResponse({'models':model_catalog(request.user),'budget':visible_budget(request.user)})


@team
@require_GET
@json_errors
def usage_summary(request):
    from .usage import dashboard
    return JsonResponse(dashboard(request.user,request.GET.get('scope')=='team'))


@team
@require_POST
@json_errors
def preferences(request):
    data=json_body(request)
    model=get_object_or_404(PoolModel,pk=int(data.get('model')),enabled=True,provider__enabled=True)
    value=allowance(request.user); value.preferred_model=model; value.save(update_fields=['preferred_model'])
    return JsonResponse({'saved':True})


def clean_history(data):
    rows=data.get('messages')
    if not isinstance(rows,list) or not 1<=len(rows)<=40: raise ValidationError('对话过长，请开始新对话。')
    result=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('role') not in ('user','assistant') or not isinstance(row.get('content'),str) or len(row['content'])>30000:
            raise ValidationError('对话内容无效。')
        result.append({'role':row['role'],'content':row['content']})
    if result[-1]['role']!='user' or (not result[-1]['content'].strip() and not data.get('images')): raise ValidationError('请填写问题或添加图片。')
    if len(json.dumps(result,ensure_ascii=False).encode())>100000: raise ValidationError('对话过长，请开始新对话。')
    return result


@team
@require_POST
@json_errors
def assistant_upload_image(request):
    # Limit pending drafts independently of completed conversation history.
    cutoff=timezone.now()-timezone.timedelta(days=1)
    AssistantImage.objects.filter(user=request.user,jobs__isnull=True,created_at__lt=cutoff).delete()
    if AssistantImage.objects.filter(user=request.user,jobs__isnull=True).count()>=20:
        raise ValidationError('待发送图片过多，请发送或移除已有图片。')
    data,width,height=image_inputs.normalize(request.FILES.get('image'))
    row=AssistantImage.objects.create(user=request.user,data=data,width=width,height=height)
    return JsonResponse(image_inputs.metadata([row])[0],status=201)


@team
@never_cache
def assistant_image(request,pk):
    row=get_object_or_404(AssistantImage,pk=pk,user=request.user)
    if request.method=='DELETE':
        if row.jobs.exists():return JsonResponse({'error':'已发送图片随对话保留，删除对话即可移除。'},status=400)
        row.delete();return JsonResponse({'deleted':True})
    if request.method!='GET':return JsonResponse({'error':'方法不支持。'},status=405)
    import base64
    response=HttpResponse(base64.b64decode(row.data.split(',',1)[1]),content_type='image/jpeg')
    response['X-Content-Type-Options']='nosniff'
    response['Content-Disposition']='inline; filename="assistant-image.jpg"'
    return response


@team
@require_POST
@json_errors
def assistant_start(request):
    from .history import prune
    prune(request.user)
    data=json_body(request); history=clean_history(data)
    job_id=None
    if data.get('request_id'):
        if not isinstance(data['request_id'],str) or len(data['request_id'])>36:
            raise ValidationError('消息标识无效。')
        nonce=uuid.UUID(data['request_id'])
        job_id=uuid.uuid5(uuid.NAMESPACE_URL, f'workbench-assistant:{required_workspace_id()}:{request.user.pk}:{nonce}')
        existing=AssistantJob.objects.select_related('conversation').filter(pk=job_id,user=request.user).first()
        if existing:
            return JsonResponse({'job':str(existing.pk),'conversation':existing.conversation_id,
                'title':existing.conversation.title if existing.conversation else ''},status=202)
    retry=None
    attached=[]
    if data.get('retry_job'):
        retry=get_object_or_404(AssistantJob,pk=data['retry_job'],user=request.user,state='error')
        from .execution import can_retry
        if not can_retry(retry):raise ValidationError('上一请求的用量尚待核对，暂不能再次调用。')
        if not retry.user_text.strip():
            raise ValidationError('原消息已不可用，请重新填写问题。')
        from .inputs import retry_history
        history=retry_history(retry)
        attached=list(retry.images.all())
    else:attached=image_inputs.owned(request.user,data.get('images',[]))
    image_row=history[0] if retry else history[-1]
    if attached and not image_row['content'].strip():image_row['content']='请分析这张图片。' if len(attached)==1 else '请分析这些图片。'
    if attached:image_row['_image_ids']=[str(row.pk) for row in attached]
    conversation=retry.conversation if retry else get_object_or_404(AssistantConversation,pk=data['conversation'],user=request.user) if data.get('conversation') else None
    if conversation:
        from .context import turn_history,size
        blocks=[]
        prior=conversation.jobs.exclude(state='error')
        if retry: prior=prior.filter(creation_order__pk__lt=retry.creation_order.pk)
        for row in reversed(list(prior.order_by('-creation_order__pk','-created_at','-pk')[:18])):
            recorded=turn_history(row)
            if recorded:
                blocks.append(recorded)
                continue
            saved=[]
            if row.user_text:
                item={'role':'user','content':row.user_text}
                previous_images=[str(image.pk) for image in row.images.all()]
                if previous_images:item['_image_ids']=previous_images
                saved.append(item)
            if row.state in ('done','cancelled') and row.result.get('text'):
                saved.append({'role':'assistant','content':clean_response(row.result['text'])[:30000]})
            if saved:blocks.append(saved)
        latest=history if retry else [history[-1]]
        history=[item for block in blocks for item in block]+latest
        # Remove complete turns so function calls retain their matching results.
        while (size(history)>100000 or sum(len(row.get('_image_ids',row.get('_images',[]))) for row in history)>8) and blocks:
            blocks.pop(0)
            history=[item for block in blocks for item in block]+latest
    from .funding import resolve,check
    from core.tenancy import scope
    payer=resolve(request.user,data.get('funding'))
    with scope(payer):
        model=get_object_or_404(PoolModel.objects.select_related('provider'),pk=int(data.get('model')),enabled=True,provider__enabled=True)
    if any(row.get('_image_ids') or row.get('_images') for row in history) and not image_inputs.supports_images(model):
        message='当前模型无法读取图片，请切换支持识图的模型；图片和文字已保留，本次未发起调用、不扣点数。' if attached else '这段对话包含图片，当前模型无法读取图片。请切换识图模型，或新建对话进行纯文字聊天；本次未发起调用、不扣点数。'
        return JsonResponse({'code':'image_not_supported','error':message},status=400)
    preferences=retry.preferences if retry else data.get('preferences',{})
    if not isinstance(preferences,dict) or any(key not in ('thinking','web') or type(value) is not bool for key,value in preferences.items()):
        raise ValidationError('助手选项无效。')
    if preferences.get('thinking') and __import__('urllib.parse',fromlist=['urlsplit']).urlsplit(model.provider.base_url).hostname!='api.deepseek.com':
        raise ValidationError('当前模型不支持手动切换思考模式。')
    context=retry.context if retry else data.get('context') or None
    if context:
        if not isinstance(context,dict) or context.get('kind') not in agent.LABELS or type(context.get('id'))!=int:
            raise ValidationError('引用资料无效。')
        if not agent.available(request.user,context['kind']).filter(pk=context['id']).exists(): raise PermissionDenied
    from .delegation import validate_grant
    authorization=None
    authorization_id=data.get('authorization') if 'authorization' in data else retry.authorization_id if retry else None
    if authorization_id:
        authorization=validate_grant(request.user,authorization_id)
        if not model.supports_tools:raise ValidationError('执行任务需要支持工具调用的模型。')
    with scope(payer):
        if not provider_key(model.provider) or not current_price(model):raise ValidationError('请先配置厂商密钥和模型价格。')
    created=False
    if conversation is None:
        conversation=AssistantConversation.objects.create(user=request.user,title=' '.join(history[-1]['content'].split())[:100])
        created=True
    try:
        options = {'preferences': preferences} if preferences else {}
        if authorization:options['authorization']=authorization
        if attached:
            options['images'] = attached
        job=agent.start(request.user,model,history,context,conversation,job_id=job_id,retry_of=retry,billing_workspace=payer,**options)
    except Exception:
        if created: conversation.delete()
        raise
    if created and job.conversation_id!=conversation.pk:conversation.delete()
    conversation=job.conversation
    return JsonResponse({'job':str(job.pk),'conversation':job.conversation_id,'title':conversation.title if conversation else ''},status=202)


def conversation_row(value):
    return {'id':value.pk,'title':value.title,'updated_at':value.updated_at.isoformat(),'running':getattr(value,'running',False)}


@team
@json_errors
def assistant_conversations(request):
    if request.method == 'POST':
        data = json_body(request)
        with transaction.atomic():
            User.objects.filter(pk=request.user.pk).update(is_active=F('is_active'))
            if data.get('action') == 'clear':
                if AssistantJob.objects.filter(user=request.user, state='running').exists():
                    raise ValidationError('请先停止正在执行的对话，完成结算后再清空。')
                used_images=list(AssistantImage.objects.filter(user=request.user,jobs__conversation__user=request.user).values_list('pk',flat=True))
                AssistantConversation.objects.filter(user=request.user).delete()
                AssistantImage.objects.filter(user=request.user,pk__in=used_images,jobs__isnull=True).delete()
                return JsonResponse({'cleared':True})
            if data.get('action') != 'retention' or type(data.get('days')) != int or data['days'] not in (0, 7, 30, 90):
                raise ValidationError('请选择有效的历史保留期限。')
            policy = allowance(request.user)
            policy.history_days = data['days']
            policy.save(update_fields=['history_days'])
            from .history import prune
            prune(request.user)
            return JsonResponse({'history_days':policy.history_days})
    if request.method != 'GET': return JsonResponse({'error':'方法不支持。'},status=405)
    rows=AssistantConversation.objects.filter(user=request.user).annotate(running=Exists(
        AssistantJob.objects.filter(conversation_id=OuterRef('pk'),state='running')))
    query=request.GET.get('q','').strip()[:100]
    if query: rows=rows.filter(title__icontains=query)
    days = Allowance.objects.filter(user=request.user).values_list('history_days',flat=True).first() or 0
    return JsonResponse({'conversations':[conversation_row(value) for value in rows[:100]],'history_days':days})


@team
@json_errors
def assistant_conversation(request,pk):
    value=get_object_or_404(AssistantConversation,pk=pk,user=request.user)
    if request.method=='POST':
        data=json_body(request)
        if data.get('action')=='delete':
            if value.jobs.filter(state='running').exists(): raise ValidationError('请先停止正在执行的对话，完成结算后再删除。')
            used_images=list(AssistantImage.objects.filter(user=request.user,jobs__conversation=value).values_list('pk',flat=True))
            value.delete()
            AssistantImage.objects.filter(user=request.user,pk__in=used_images,jobs__isnull=True).delete()
            return JsonResponse({'deleted':True})
        if data.get('action')!='rename': raise ValidationError('操作无效。')
        title=data.get('title')
        if not isinstance(title,str) or not title.strip() or len(title.strip())>100: raise ValidationError('名称需为 1–100 个字符。')
        value.title=title.strip(); value.save(update_fields=['title','updated_at'])
        return JsonResponse(conversation_row(value))
    if request.method!='GET': return JsonResponse({'error':'方法不支持。'},status=405)
    rows=[]; active=None
    jobs=list(reversed(list(value.jobs.prefetch_related('inputs','images').order_by('-creation_order__pk','-created_at','-pk')[:100])))
    shown={job.pk for job in jobs};superseded={job.retry_of_id for job in jobs if job.retry_of_id}
    for job in jobs:
        if job.user_text and job.retry_of_id not in shown: rows.append({'role':'user','text':job.user_text,'context':job.context,'images':image_inputs.metadata(job.images.all())})
        from .inputs import metadata
        rows.extend({'role':'user','text':value.text,'input':metadata(value)} for value in job.inputs.all())
        if job.state=='running': active=str(job.pk)
        elif job.result and job.pk not in superseded:
            row={'role':'assistant','text':job.result.get('error') or clean_response(job.result.get('text','')),'result':display_result(job.result)}
            if job.state=='error':
                from .execution import can_continue,can_retry
                row['retry']={'job':str(job.pk),'text':job.user_text,'context':job.context,
                    'can_continue':can_continue(job),'can_retry':can_retry(job)}
                attached=image_inputs.metadata(job.images.all())
                if attached:row['retry']['images']=attached
            rows.append(row)
    return JsonResponse({**conversation_row(value),'messages':rows,'active_job':active})


@team
@json_errors
@never_cache
def assistant_job(request,pk):
    job=get_object_or_404(AssistantJob,pk=pk,user=request.user)
    if request.method=='POST':
        data=json_body(request)
        if data.get('action')=='append':
            if set(data)-{'action','text','request_id'}:raise ValidationError('补充要求不能修改本轮模型或授权。')
            from .inputs import enqueue,metadata
            value=enqueue(job,request.user,data.get('text'),data.get('request_id'))
            return JsonResponse({'job':str(job.pk),'input':metadata(value)},status=202)
        if data.get('action')=='continue':
            from .execution import continue_job,kick
            job=continue_job(job,request.user,data.get('authorization'))
            kick(job.pk)
            return JsonResponse({'job':str(job.pk),'state':job.state})
        if data.get('action') not in (None,'stop'):raise ValidationError('操作无效。')
        AssistantJob.objects.filter(pk=job.pk,user=request.user,state='running').update(cancel_requested=True)
        return JsonResponse({'stopping':True})
    if request.method!='GET': return JsonResponse({'error':'方法不支持。'},status=405)
    from .execution import can_continue,can_retry,kick
    if job.state=='running' and job.execution.get('version')==1:
        kick(job.pk)
    elif job.state=='running' and job.heartbeat_at<timezone.now()-timezone.timedelta(minutes=20):
        job.state='error'; job.result={'error':'服务已重启或本轮超时；已发生的调用可在 API 池查看。'}
        job.finished_at=timezone.now(); job.save(update_fields=['state','result','finished_at'])
    try:cursor=int(request.GET.get('after','0'))
    except (TypeError,ValueError):raise ValidationError('进度标识无效。')
    if not 0<=cursor<=2**63-1:raise ValidationError('进度标识无效。')
    with transaction.atomic():
        job=AssistantJob.objects.get(pk=job.pk,user=request.user)
        allowed={'input_id','input_ids','item_id','tool','tool_call_id','status','receipt','call_id','state','resumed'}
        events=[{'sequence':row.sequence,'kind':row.kind,'payload':{key:value for key,value in row.payload.items() if key in allowed}}
            for row in job.events.filter(sequence__gt=cursor)[:100]]
        from .inputs import metadata
        delivered=events[-1]['sequence'] if events else min(cursor,job.event_sequence)
        return JsonResponse({'state':job.state,'activity':job.activity,'result':display_result(job.result),
            'queued':job.state=='running' and job.lease_token is None,'can_continue':can_continue(job),'can_retry':can_retry(job),
            'events':events,'cursor':delivered,'has_more_events':delivered<job.event_sequence,'sequence':job.event_sequence,
            'inputs':[metadata(value) for value in job.inputs.all()],
            'request':{'text':job.user_text,'context':job.context,'conversation':job.conversation_id,'images':image_inputs.metadata(job.images.all())}})


@team
@require_GET
@json_errors
def references(request):
    kind=request.GET.get('kind','task'); query=request.GET.get('q','')[:100]
    value=agent.run_tool(request.user,'search_workspace',{'kind':kind,'query':query})
    return JsonResponse(value)


@team
@json_errors
@never_cache
def assistant_capabilities(request):
    from .tool_registry import registry
    from .delegation import issue,permitted_actions
    from .models import AgentGrant
    if request.method=='POST':
        data=json_body(request)
        if data.get('action')=='grant':
            grant=issue(request.user,data.get('project'),data.get('actions'),hours=data.get('hours',1),max_operations=data.get('max_operations',20))
            return JsonResponse({'id':str(grant.pk)},status=201)
        if data.get('action')=='revoke':
            with transaction.atomic():
                changed=AgentGrant.objects.filter(pk=data.get('id'),user=request.user,revoked_at__isnull=True).update(revoked_at=timezone.now())
                if changed:AssistantJob.all_objects.filter(user=request.user,authorization_id=data['id'],state='running').update(cancel_requested=True)
            if not changed:raise ValidationError('授权已撤销或不存在。')
            return JsonResponse({'revoked':True})
        if data.get('action')=='plugin':
            plugin=data.get('plugin');enabled=data.get('enabled')
            from .plugins import set_enabled
            set_enabled(request.user,plugin,enabled)
            return JsonResponse({'saved':True})
        raise ValidationError('操作无效。')
    if request.method!='GET':return JsonResponse({'error':'方法不支持。'},status=405)
    projects=[]
    for project in agent.available(request.user,'project').select_related('workspace__team').filter(name__icontains=request.GET.get('q','')[:100]).order_by('-pk')[:100]:
        actions=permitted_actions(request.user,project)
        if actions:projects.append({'id':project.pk,'title':project.name,'workspace':project.workspace.name,'actions':actions})
    grants=[{'id':str(grant.pk),'project':grant.project_id,'title':grant.project.name,'actions':grant.actions,
        'expires_at':grant.expires_at.isoformat(),'remaining':grant.max_operations-grant.used_operations}
        for grant in AgentGrant.objects.filter(user=request.user,revoked_at__isnull=True,expires_at__gt=timezone.now(),
            project__workspace__active=True,project__archived_at__isnull=True).select_related('project').order_by('-created_at')[:30]
        if agent.available(request.user,'project').filter(pk=grant.project_id).exists()]
    from .plugins import catalog as plugin_catalog
    return JsonResponse({'plugins':plugin_catalog(request.user),
        'projects':projects,'grants':grants})


@team
def manage(request):
    require_pool_owner(request)
    from .quotas import snapshot
    provider_form=ProviderForm(); model_form=ModelForm(initial={'currency':'CNY'})
    settings_form=SettingsForm(instance=pool_settings()); error=''; action=request.POST.get('action')
    try:
        if request.method=='POST':
            if action=='provider':
                instance=Provider.objects.filter(pk=request.POST.get('id')).first() if request.POST.get('id','').isdigit() else None
                provider_form=ProviderForm(request.POST,instance=instance)
                if provider_form.is_valid():
                    with transaction.atomic():
                        value=provider_form.save(); store_key(value,provider_form.cleaned_data['api_key'])
                        from .routing import reset_health
                        reset_health(value)
                    notices.success(request,'厂商连接已保存。'); return redirect(pool_destination('api_manage'))
            elif action=='model':
                instance=PoolModel.objects.filter(pk=request.POST.get('id')).first() if request.POST.get('id','').isdigit() else None
                model_form=ModelForm(request.POST,instance=instance)
                if model_form.is_valid():
                    with transaction.atomic():
                        value=model_form.save()
                        if value.price_mode=='manual': save_price(value,model_form.cleaned_data,value.price_source or '管理员登记')
                    if value.price_mode=='auto':
                        refresh_prices()
                    if not current_price(value): notices.warning(request,'连接已保存；此型号的公开价格暂不可用，负责人可设置自定义价格。')
                    notices.success(request,'模型与新价格版本已保存。'); return redirect(pool_destination('api_manage'))
            elif action=='settings':
                settings_form=SettingsForm(request.POST,instance=pool_settings())
                if settings_form.is_valid(): settings_form.save(); notices.success(request,'团队额度已保存。'); return redirect(pool_destination('api_manage'))
            elif action=='toggle_model':
                model=get_object_or_404(PoolModel,pk=int(request.POST.get('id')))
                model.enabled=not model.enabled; model.save(update_fields=['enabled'])
                return redirect(pool_destination('api_manage'))
            elif action=='toggle_provider':
                provider=get_object_or_404(Provider,pk=int(request.POST.get('id')))
                provider.enabled=not provider.enabled; provider.save(update_fields=['enabled'])
                return redirect(pool_destination('api_manage'))
            elif action=='reset_provider_health':
                from .routing import reset_health
                reset_health(get_object_or_404(Provider,pk=request.POST.get('id')))
                notices.success(request,'连接已恢复可调用状态，下一次请求会重新检查上游。')
                return redirect(reverse('api_manage')+'#pool-model-management')
            elif action=='reset_budget':
                scope='team' if request.POST.get('target')=='team' else 'user:'+str(get_object_or_404(User,pk=int(request.POST.get('user'))).pk)
                reset_budget(scope,request.POST.get('period','both'),actor=request.user,reason=request.POST.get('reason','管理员恢复额度'))
                notices.success(request,'额度已重置，历史费用和未完成调用的预留保留。')
                return redirect(pool_destination('api_manage'))
            elif action=='grant_points':
                issue_points(request)
                return redirect(pool_destination('api_manage'))
            elif action=='save_plan':
                save_plan(request)
                return redirect(pool_destination(scope='team'))
            elif action=='reset_plans':
                reset_member_plans(request.user); notices.success(request,'所有成员本周基础额度已重置，额外点数和历史费用保留。')
                return redirect(pool_destination(scope='team'))
            elif action=='refresh':
                count=refresh_prices(force=True); notices.success(request,f'已处理 {count} 个模型的每日价格记录。'); return redirect(pool_destination('api_manage'))
            elif action=='reconcile':
                call=get_object_or_404(Call,pk=request.POST.get('call'),status__in=['unknown','running'])
                if call.status=='running' and call.created_at>timezone.now()-timezone.timedelta(minutes=5): raise ValidationError('调用仍在执行，请稍后核对。')
                cost=Decimal(request.POST.get('cost',''))
                if not cost.is_finite() or cost<0 or cost>100000: raise ValidationError('核对金额无效。')
                settle(call,None,cost_override=cost)
                notices.success(request,'费用已核对并结算额度。'); return redirect(pool_destination('api_manage'))
            elif action=='reconcile_auto':
                from .operations import reconcile
                result=reconcile(limit=5,timeout=5)
                notices.success(request,f"已查询 {result['checked']} 笔，结算 {result['settled']} 笔已确认费用；其余保留待核对。")
                return redirect(pool_destination('api_manage'))
        elif request.GET.get('provider','').isdigit():
            provider_form=ProviderForm(instance=get_object_or_404(Provider,pk=request.GET['provider']))
        elif request.GET.get('model','').isdigit():
            value=get_object_or_404(PoolModel,pk=request.GET['model']); price=current_price(value)
            if not value.enabled or not value.provider.enabled:
                notices.info(request,'请先启用连接和模型，再填写价格。')
                return redirect(reverse('api_manage')+'#pool-model-management')
            initial={field:getattr(price,field) for field in ('currency','input_rate','output_rate','cached_rate','cache_write_rate','cny_exchange_rate')} if price else {}
            model_form=ModelForm(instance=value,initial=initial)
    except (ValidationError,InvalidOperation,ValueError,TypeError,OverflowError) as exc:
        error=' '.join(exc.messages) if isinstance(exc,ValidationError) else '输入无效。'
    accounts=[]
    for user in team_users().filter(is_active=True).order_by('username'):
        if perms.is_team_member(user): accounts.append({'user':user,'allowance':allowance(user),'budget':summary(user)})
    saved_models=list(PoolModel.objects.select_related('provider','fallback_model__provider').order_by('provider__name','model_id'))
    models=[model for model in saved_models if model.enabled and model.provider.enabled]
    from .vendor_prices import source_info
    for model in models:
        model.current_price=current_price(model); model.has_price=model.current_price is not None
        model.auto_price_info=source_info(model.provider)
    models.sort(key=lambda model:(model.has_price,model.provider.name.lower(),model.model_id.lower()))
    providers=Provider.objects.select_related('relay_health').order_by('name')
    models_by_provider={}
    for model in saved_models: models_by_provider.setdefault(model.provider_id,[]).append(model)
    from .operations import dashboard as relay_dashboard
    return render(request,'aihub/manage.html',{'relay_operations':relay_dashboard(),'provider_form':provider_form,'model_form':model_form,'settings_form':settings_form,
        'providers':[{'item':p,'models':models_by_provider.get(p.pk,[]),'has_key':bool(provider_key(p)),'quota':snapshot(p),
            'relay_paused':bool(getattr(p,'relay_health',None) and p.relay_health.cooldown_until)} for p in providers],
        'provider_connections':[{'id':p.pk,'preset':discovery.preset_for(p),'name':p.name,'protocol':p.protocol,'base_url':p.base_url} for p in providers],
        'presets':discovery.PRESETS,
        'models':models,'saved_models':saved_models,'missing_price_count':sum(not model.has_price for model in models),'accounts':accounts,'error':error,
        'pending_calls':Call.objects.filter(status__in=['unknown','running']).select_related('user','model__provider','price')[:50]})


@team
@require_POST
@json_errors
def provider_quota(request,pk):
    require_pool_owner(request)
    from .quotas import refresh
    provider=get_object_or_404(Provider,pk=pk)
    data=json_body(request)
    kind=data.get('kind',provider.quota_kind)
    if kind not in ('auto','plan','account'):raise ValidationError('额度类型无效。')
    if kind!=provider.quota_kind:
        provider.quota_kind=kind;provider.save(update_fields=['quota_kind'])
    return JsonResponse(refresh(provider))


def api_authorization(request):
    auth=request.headers.get('Authorization','')
    values=[auth[7:].strip()] if auth[:7].lower()=='bearer ' else []
    values.extend(request.headers.get(name,'').strip() for name in ('x-api-key','x-goog-api-key') if request.headers.get(name))
    if request.path.startswith('/v1beta/') and request.GET.get('key'):values.append(request.GET['key'])
    return 'Bearer '+values[0] if values and len(set(values))==1 else ''


def bearer(view):
    @wraps(view)
    def scoped_token(request,*args,**kwargs):
        from core.tenancy import scope
        from core.models import TeamMembership
        auth=api_authorization(request)
        digest=hashlib.sha256(auth[7:].strip().encode()).hexdigest() if auth.startswith('Bearer ') else ''
        token=MemberToken.all_objects.filter(digest=digest,revoked_at__isnull=True).first() if digest else None
        if token and (not token.team_id or not token.workspace.active or token.workspace.kind!='team' or not TeamMembership.objects.filter(team_id=token.team_id,user_id=token.user_id,
                active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).exists()):
            return relay_error('凭证所属团队的成员资格已失效。',403,'permission_denied')
        from core.workspace_audit import acting_as
        with scope(token.workspace if token else None), acting_as(token.user if token else None):
            return wrapper(request,*args,**kwargs)
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        auth=api_authorization(request)
        if not auth.startswith('Bearer '): return relay_error('需要你的 API Key。',401,'invalid_api_key')
        digest=hashlib.sha256(auth[7:].strip().encode()).hexdigest()
        token=MemberToken.objects.select_related('user').filter(digest=digest,revoked_at__isnull=True).first()
        if not token: return relay_error('API Key 无效或已撤销。',401,'invalid_api_key')
        from .relay import check_token, RelayError
        try:check_token(token)
        except RelayError as error:return relay_error(' '.join(error.messages),error.http_status,error.api_code)
        try: require_member(token.user)
        except PermissionDenied: return relay_error('账户调用权限不可用。',403,'permission_denied')
        request.pool_user=token.user
        request.pool_token=token
        from .rate_limits import gate, RateLimited
        from contextlib import nullcontext
        lease=gate(token.user, token) if request.method=='POST' else nullcontext()
        transferred=False; entered=False
        try:
            lease.__enter__(); entered=True
            response=view(request,*args,**kwargs)
            if response.streaming:
                from .gateway import ScopedStream
                iterator=response._iterator
                closer=getattr(iterator,'close',None)
                if closer in response._resource_closers: response._resource_closers.remove(closer)
                response.streaming_content=ScopedStream(iterator,token,lease)
                transferred=True
            return response
        except RateLimited as error:
            response=relay_error(str(error),429,'rate_limit_exceeded')
            response['Retry-After']='60'
            return response
        except OperationalError:
            response=relay_error('服务正忙，请稍后重试；已发生的用量仍以调用账目为准。',503,'server_busy')
            response['Retry-After']='2'
            return response
        finally:
            if entered and not transferred: lease.__exit__(None,None,None)
    return scoped_token


@csrf_exempt
@bearer
@require_GET
@json_errors
def api_models(request):
    rows={}
    for model in model_catalog(request.pool_user):
        if not model['configured'] or request.pool_token.allowed_models and model['id'] not in request.pool_token.allowed_models:continue
        row=rows.setdefault(model['alias'],{'id':model['alias'],'object':'model','type':'model','display_name':model['label'],
            'owned_by':model['provider'],'created':0,'created_at':'1970-01-01T00:00:00Z','native_model':model['model_id'],
            'max_output_tokens':model['max_output_tokens'],'default_output_tokens':model['default_output_tokens']})
        row['max_output_tokens']=max(row['max_output_tokens'],model['max_output_tokens'])
    data=list(rows.values())
    return JsonResponse({'object':'list','data':data,'has_more':False,'first_id':data[0]['id'] if data else None,'last_id':data[-1]['id'] if data else None})


@csrf_exempt
@bearer
@require_GET
@json_errors
def api_experiments(request):
    records=callable_experiments(request.pool_user)
    if request.pool_token.experiment_bound:records=records.filter(pk=request.pool_token.experiment_id)
    if request.pool_token.project_bound:records=records.filter(project_id=request.pool_token.project_id)
    query=request.GET.get('q','').strip()[:200]
    if query:records=records.filter(Q(number__icontains=query)|Q(title__icontains=query))
    rows=list(records.values('id','number','title','project_id','status')[:201])
    return JsonResponse({'object':'list','data':rows[:200],'has_more':len(rows)>200})


@csrf_exempt
@bearer
@require_POST
@json_errors
def api_chat(request):
    from .relay import read_body, chat_payload
    data=read_body(request)
    token=request.pool_token
    if token.experiment_bound:
        if not token.experiment_id:raise ValidationError('这个 API Key 关联的实验已删除，请撤销并重新生成 Key。')
        if 'experiment_id' in data and (type(data['experiment_id']) is not int or data['experiment_id']!=token.experiment_id):
            raise ValidationError('请求中的实验与 API Key 关联的实验不一致，请使用对应实验的 Key。')
        experiment_id=token.experiment_id
    else:
        experiment_id=data.get('experiment_id')
    project_id=data.get('project_id')
    if token.project_bound:
        if not token.project_id:raise ValidationError('这个 API Key 关联的项目已删除，请撤销并重新生成。')
        if 'project_id' in data and (type(project_id) is not int or project_id!=token.project_id):raise ValidationError('请求中的项目与 API Key 关联的项目不一致。')
        project_id=token.project_id
    project,experiment=independent_context(request.pool_user,experiment_id,project_id)
    from .channels import resolve_model,public_name
    model=resolve_model(request.pool_user,data.get('model'),token,limit=data.get('max_completion_tokens',data.get('max_tokens')))
    matches=[{'alias':public_name(model)}]
    from .relay import check_token
    check_token(token,model)
    payload=chat_payload(data,model)
    history,tools,limit,options=payload['messages'],payload['tools'],payload['limit'],payload['options']
    if data.get('stream'):
        from .gateway import RoutedChatStream
        stream=RoutedChatStream(request.pool_user,model,history,tools,limit,options,matches[0]['alias'],payload['include_usage'],project,experiment,api_token=token)
        response=StreamingHttpResponse(stream,content_type='text/event-stream; charset=utf-8')
        response['Cache-Control']='no-cache, no-store'
        response['X-Accel-Buffering']='no'
        response['X-Request-ID']=str(stream.call.pk)
        return response
    from .routing import execute_routed
    result=execute_routed(request.pool_user,model,history,tools,limit,options,project,experiment,token)
    counts=result['counts']; message={'role':'assistant','content':result['text'] or None}
    if result['tool_calls']: message['tool_calls']=result['tool_calls']
    if result.get('reasoning'): message['reasoning_content']=result['reasoning']
    native_message=result.get('assistant_message') or {}
    if 'reasoning_details' in native_message: message['reasoning_details']=native_message['reasoning_details']
    usage=None if counts is None else {'prompt_tokens':counts['input_tokens'],'completion_tokens':counts['output_tokens'],
        'total_tokens':counts['input_tokens']+counts['output_tokens'],'prompt_tokens_details':{'cached_tokens':counts['cached_tokens'],'cache_write_tokens':counts['cache_write_tokens']},
        'completion_tokens_details':{'reasoning_tokens':counts['reasoning_tokens']}}
    from .providers import compatible_finish_reason
    response=JsonResponse({'id':result['request_id'],'object':'chat.completion','created':int(timezone.now().timestamp()),'model':matches[0]['alias'],
        'choices':[{'index':0,'message':message,'finish_reason':compatible_finish_reason(result)}],
        'usage':usage,'workbench':{'team_id':token.team_id,'experiment_id':experiment.pk if experiment else None,'experiment_number':experiment.number if experiment else None,
            'project_id':project.pk if project else None,'cost':result['cost'],'currency':result['currency'],'cost_cny':result['cost_cny'],
            'price_version':result['price_version'],'status':result['status'],
            'upstream_finish_reason':result.get('finish_reason'),
            **{key:result[key] for key in ('request_id','call_id','attempt_count','selected_model')}}})
    response['X-Request-ID']=result['request_id'];response['Cache-Control']='no-store'
    return response


@csrf_exempt
@bearer
@require_GET
@relay_errors
def api_key_info(request):
    from .relay import token_usage
    from django.conf import settings
    token=request.pool_token
    config=pool_settings()
    response=JsonResponse({'object':'relay.key','name':token.label,'prefix':token.prefix,'team_id':token.team_id,
        'expires_at':token.expires_at.isoformat() if token.expires_at else None,
        'last_used_at':token.last_used_at.isoformat() if token.last_used_at else None,
        'allowed_models':[m['alias'] for m in model_catalog(request.pool_user) if m['configured'] and (not token.allowed_models or m['id'] in token.allowed_models)],
        'quota':token_usage(token),'budget':visible_budget(request.pool_user),'points_per_cny':100,
        'limits':{'request_body_bytes':settings.WORKBENCH_RELAY_MAX_REQUEST_BYTES,
                  'context_bytes':settings.WORKBENCH_RELAY_MAX_CONTEXT_BYTES,
                  'messages':settings.WORKBENCH_RELAY_MAX_MESSAGES,'tools':settings.WORKBENCH_RELAY_MAX_TOOLS,
                  **{name:getattr(config,name) for name in CallLimitsForm._meta.fields}}})
    response['Cache-Control']='no-store'
    return response


@csrf_exempt
@bearer
@require_GET
@relay_errors
def api_usage(request):
    from .relay import token_usage, RelayError
    query=Call.objects.filter(api_token=request.pool_token).select_related('model','price')
    identifier=request.GET.get('call_id')
    if identifier:
        try:identifier=uuid.UUID(identifier)
        except (ValueError,TypeError):raise RelayError('call_id 无效。') from None
        query=query.filter(Q(pk=identifier)|Q(group_id=identifier,purpose='api'))
    page=Paginator(query.order_by('-created_at','-pk'),50).get_page(request.GET.get('page'))
    response=JsonResponse({'object':'list','data':[{'id':str(call.pk),'model':call.public_model or str(call.model.provider_id)+'/'+call.model.model_id,
        'upstream_model':call.upstream_model or call.model.model_id,
        'created':int(call.created_at.timestamp()),'status':call.status,'input_tokens':call.input_tokens,'output_tokens':call.output_tokens,
        'cached_tokens':call.cached_tokens,'reasoning_tokens':call.reasoning_tokens,
        'api_kind':call.api_kind,'latency_ms':call.latency_ms,'first_token_ms':call.first_token_ms,
        'request_bytes':call.request_bytes,'estimated_input_tokens':call.estimated_input_tokens,'estimate_method':call.estimate_method,
        'cost_cny':str(call.cost_cny) if call.cost_cny is not None else None,'reserved_cny':str(call.reserved_cny) if call.status in ('running','unknown') else '0',
        'error_code':call.error_code,'price_version':call.price_id,
        'request_id':str(call.group_id or call.pk)} for call in page],
        'page':page.number,'has_more':page.has_next(),'quota':token_usage(request.pool_token)})
    response['Cache-Control']='no-store'
    return response


@login_required
@require_GET
@json_errors
def web_preview(request):
    from .web_tools import read_web
    from django.core.cache import cache
    require_member(request.user)
    key=f'web-preview:{required_workspace_id()}:{request.user.pk}'
    if not cache.add(key,True,1):return JsonResponse({'error':'读取过于频繁，请稍后重试。'},status=429)
    return JsonResponse(read_web(request.GET.get('url','')))


@csrf_exempt
@bearer
@require_POST
@json_errors
def api_experiment_run(request, pk):
    from core.models import ExperimentRun
    data=json_body(request)
    token=request.pool_token
    if token.experiment_bound and token.experiment_id!=pk:raise ValidationError('只能向当前 Key 关联的实验提交运行记录。')
    _,experiment=independent_context(request.pool_user,pk)
    if token.project_bound and experiment.project_id!=token.project_id:raise ValidationError('只能向当前 Key 关联项目中的实验提交运行记录。')
    title=data.get('title','API 运行结果');result=data.get('result','');parameters=data.get('parameters','');status=data.get('status','completed')
    if not isinstance(title,str) or not title.strip() or len(title)>160 or not isinstance(result,str) or len(result)>30000 or not isinstance(parameters,str) or len(parameters)>10000 or status not in ('running','completed','failed'):raise ValidationError('运行记录格式或长度无效。')
    run_id=data.get('run_id')
    if run_id is not None:
        if type(run_id) is not int or run_id<1:raise ValidationError('运行编号无效。')
        run=get_object_or_404(ExperimentRun,pk=run_id,experiment=experiment,created_by=request.pool_user)
        run.title=title.strip();run.result=result;run.parameters=parameters;run.status=status;run.save(update_fields=['title','result','parameters','status'])
    else:
        run=ExperimentRun.objects.create(experiment=experiment,created_by=request.pool_user,title=title.strip(),result=result,parameters=parameters,status=status)
    return JsonResponse({'id':run.pk,'experiment_id':pk},status=200 if run_id else 201)
