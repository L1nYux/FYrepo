import hashlib
import json
import math
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from django.contrib import messages as notices
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core import signing
from django.core.paginator import Paginator
from django.db import transaction, OperationalError
from django.db.models import Sum, Count, F, Q, Exists, OuterRef
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from core import permissions as perms
from core.models import Project, Experiment
from . import agent
from . import discovery
from .permissions import is_pool_owner,require_pool_owner,visible_budget
from .models import Provider, PoolModel, DailyPrice, PriceVersion, MemberToken, Call, AssistantJob, AssistantConversation, Allowance, PointGrant
from .forms import ProviderForm, ModelForm, SimplePriceForm, SettingsForm, PlanForm, PointGrantForm
from .automatic_prices import enrich_catalog, automatic_price, AUTO
from .prices import current_price, save_price, refresh_prices
from .service import provider_key, store_key, require_member, summary, pool_settings, allowance, create_token, execute, settle, context_objects,reset_budget, grant_points, reset_member_plans


def issue_points(request):
    require_pool_owner(request)
    form = PointGrantForm(request.POST)
    if not form.is_valid(): raise ValidationError('请输入有效的额外点数，或刷新页面后重新发放。')
    all_members=request.POST.get('user')=='all'
    users=[u for u in User.objects.filter(is_active=True).order_by('pk') if perms.is_team_member(u)] if all_members else [get_object_or_404(User, pk=int(request.POST.get('user')))]
    added=0
    with transaction.atomic():
        config=pool_settings(); type(config).objects.filter(pk=config.pk).update(enabled=F('enabled'))
        for user in users:
            grant_id=uuid.uuid5(form.cleaned_data['grant_id'],str(user.pk))
            added+=int(grant_points(user,request.user,form.cleaned_data['points'],grant_id))
    notices.success(request, f'已为 {added} 位成员发放额外点数，跨周保留。' if added else '这笔点数已经发放，无需重复操作。')


def save_plan(request):
    require_pool_owner(request)
    form=PlanForm(request.POST)
    if not form.is_valid(): raise ValidationError('请输入有效的每周点数（整数，0 表示暂停基础额度）。')
    config=pool_settings()
    with transaction.atomic():
        type(config).objects.filter(pk=config.pk).update(default_weekly_limit=form.cleaned_data['points']/100)
    notices.success(request,'统一 Plan 已保存，对所有现有成员和新成员立即生效；本周已用点数保留。')


def team(view):
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        if not request.user.is_authenticated:
            if wrapper.expects_json or request.headers.get('Authorization', '').startswith('Bearer '):
                return JsonResponse({'error':'登录已失效，请重新登录。'}, status=401)
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        try:
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
        except ValidationError as error: return JsonResponse({'error':' '.join(error.messages)},status=400)
        except PermissionDenied: return JsonResponse({'error':'当前账户无权执行。'},status=403)
        except (ValueError,TypeError,KeyError,InvalidOperation): return JsonResponse({'error':'参数无效。'},status=400)
    return wrapper


def json_body(request):
    if len(request.body)>220000: raise ValidationError('请求过长。')
    data=json.loads(request.body)
    if not isinstance(data,dict): raise ValidationError('请求格式无效。')
    return data


def model_catalog(user):
    require_member(user); result=[]; owner=is_pool_owner(user)
    for model in PoolModel.objects.filter(enabled=True,provider__enabled=True).select_related('provider'):
        price=current_price(model); daily=model.daily_prices.order_by('-day').first()
        result.append({'id':model.pk,'provider_id':model.provider_id,'provider':model.provider.name,'model_id':model.model_id,
            'alias':str(model.provider_id)+'/'+model.model_id,'label':discovery.model_label(model.model_id,str(model)),'supports_tools':model.supports_tools,
            'configured':bool(provider_key(model.provider)) and price is not None,
            'input_rate':str(price.input_rate) if price else None,'output_rate':str(price.output_rate) if price else None,
            'currency':price.currency if price else '', 'price_status':daily.get_status_display() if daily else '尚无每日记录',
            'price_day':str(daily.day) if daily else None})
        if not owner:
            for name in ('input_rate','output_rate','currency','price_status','price_day'): result[-1].pop(name,None)
    return result


@team
def pool(request):
    fresh_token=''
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='new_token':
            try: fresh_token=create_token(request.user,request.POST.get('label','个人调用'))
            except ValidationError as error: notices.error(request,' '.join(error.messages))
        elif action=='revoke_token':
            MemberToken.objects.filter(pk=request.POST.get('id'),user=request.user).update(revoked_at=timezone.now())
            return redirect('api_pool')
        elif action=='reset_budget':
            require_pool_owner(request)
            try:
                scope='team' if request.POST.get('target')=='team' else 'user:'+str(get_object_or_404(User,pk=int(request.POST.get('user'))).pk)
                reset_budget(scope,request.POST.get('period','both'))
            except (ValidationError,ValueError,TypeError,OverflowError) as error:
                notices.error(request,' '.join(error.messages) if isinstance(error,ValidationError) else '请选择有效成员。')
            else:
                notices.success(request,'额度已重置，历史费用和未完成调用的预留保留。')
            return redirect(reverse('api_pool')+'?scope=team')
        elif action=='grant_points':
            require_pool_owner(request)
            try: issue_points(request)
            except (ValidationError, ValueError, TypeError, OverflowError) as error:
                notices.error(request,' '.join(error.messages) if isinstance(error,ValidationError) else '请选择有效成员。')
            return redirect(reverse('api_pool')+'?scope=team')
        elif action=='save_plan':
            require_pool_owner(request)
            try: save_plan(request)
            except ValidationError as error: notices.error(request,' '.join(error.messages))
            return redirect(reverse('api_pool')+'?scope=team')
        elif action=='reset_plans':
            require_pool_owner(request)
            reset_member_plans(); notices.success(request,'所有成员的本周基础额度已重置，额外点数和历史费用保留。')
            return redirect(reverse('api_pool')+'?scope=team')
        elif action=='settings':
            require_pool_owner(request)
            form=SettingsForm(request.POST,instance=pool_settings())
            if form.is_valid(): form.save(); notices.success(request,'额度已保存。')
            else: notices.error(request,' '.join(str(e) for errors in form.errors.values() for e in errors))
            return redirect(reverse('api_pool')+'?scope=team')
    calls=Call.objects.select_related('user','model__provider','price','project')
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
    from .usage import dashboard
    return render(request,'aihub/pool.html',{'budget':visible_budget(request.user),'catalog':catalog,'page':page,'totals':totals,
        'usage':dashboard(request.user,scope=='team'),'pool_settings':pool_settings() if is_pool_owner(request) else None,'batch_grant_id':str(uuid.uuid4()),
        'point_grants':(PointGrant.objects.all() if scope=='team' else PointGrant.objects.filter(user=request.user)).select_related('user','issued_by').order_by('-created_at')[:30],
        'tokens':MemberToken.objects.filter(user=request.user).order_by('-pk'),'fresh_token':fresh_token,'scope':scope,
        'providers':Provider.objects.filter(Q(enabled=True)|Q(models__isnull=False)).distinct() if is_pool_owner(request) else [],'selected_provider':provider,'selected_model':model,'selected_month':month,
        'by_member':by_member,'price_history':PriceVersion.objects.select_related('model__provider').all()[:50] if is_pool_owner(request) else [],
        'daily':DailyPrice.objects.select_related('model__provider','price').order_by('-day','model_id')[:50] if is_pool_owner(request) else []})


@team
def assistant(request):
    return render(request,'aihub/assistant.html',{'context_kind':request.GET.get('kind',''),'context_id':request.GET.get('id','')})


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
    price_note,fx=enrich_catalog(SimpleNamespace(**values),rows)
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
    return JsonResponse({'provider':item.pk if item else '', 'models':rows,'ticket':ticket,'truncated':truncated,'price_note':price_note,'exchange':fx})


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
                'label':row['label'],'supports_tools':row['supports_tools'],'max_output_tokens':row['max_output_tokens'],'output_parameter':row['output_parameter']})
            model.enabled=True; model.save(update_fields=['enabled'])
            price=current_price(model)
            if (price is None or price.source.startswith((AUTO,'官方 Flash 高峰参考价'))) and row.get('price'):
                proposed=row['price']; fx=proposed.get('cny_exchange_rate') or data.get('exchange_rate')
                if proposed['currency']=='CNY' or fx:
                    save_price(model,{**proposed,'cny_exchange_rate':1 if proposed['currency']=='CNY' else fx},proposed['source'])
                    price=current_price(model)
            if price is None: missing.append({'id':model.pk,'label':str(model)})
        # Only the list just fetched is affected; unlisted existing models keep their settings.
        provider.models.filter(model_id__in=available.keys()).exclude(model_id__in=selected).update(enabled=False)
        store_key(provider,catalog['key'])
    discard(proposal)
    return JsonResponse({'saved':True,'missing_prices':missing})


@team
@require_POST
@json_errors
def update_model_price(request):
    require_pool_owner(request)
    data=json_body(request); model=get_object_or_404(PoolModel,pk=data.get('id'))
    if data.get('action')=='automatic':
        try: proposed=automatic_price(model.provider,model.model_id,force=True)
        except Exception: raise ValidationError('自动读取暂时失败，已有价格已保留；请稍后重试。') from None
        if not proposed: raise ValidationError('这个厂商暂未提供可自动读取的价格，只需补输入和输出单价。')
        save_price(model,proposed,proposed['source'])
    else:
        form=SimplePriceForm(data)
        if not form.is_valid(): raise ValidationError(' '.join(str(e) for errors in form.errors.values() for e in errors))
        save_price(model,form.cleaned_data,'管理员登记')
    price=current_price(model)
    DailyPrice.objects.update_or_create(model=model,day=timezone.localdate(),defaults={
        'price':price,'status':'verified' if data.get('action')=='automatic' else 'manual','note':price.source[:300]})
    return JsonResponse({'saved':True,'input_rate':str(price.input_rate),'output_rate':str(price.output_rate),'currency':price.currency,'source':price.source})


@team
@require_GET
@json_errors
def catalog(request): return JsonResponse({'models':model_catalog(request.user),'budget':visible_budget(request.user)})


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
    if result[-1]['role']!='user' or not result[-1]['content'].strip(): raise ValidationError('请填写问题。')
    if len(json.dumps(result,ensure_ascii=False).encode())>100000: raise ValidationError('对话过长，请开始新对话。')
    return result


@team
@require_POST
@json_errors
def assistant_start(request):
    from .history import prune
    prune(request.user)
    data=json_body(request); history=clean_history(data)
    conversation=get_object_or_404(AssistantConversation,pk=data['conversation'],user=request.user) if data.get('conversation') else None
    if conversation:
        saved=[]
        for row in reversed(list(conversation.jobs.order_by('-created_at')[:18])):
            if row.user_text: saved.append({'role':'user','content':row.user_text})
            if row.state in ('done','cancelled') and row.result.get('text'):
                saved.append({'role':'assistant','content':row.result['text'][:30000]})
        history=saved[-20:]+[history[-1]]
        # Keep recent turns within the same request size limit as a new conversation.
        while len(json.dumps(history,ensure_ascii=False).encode())>100000 and len(history)>1: history.pop(0)
    model=get_object_or_404(PoolModel.objects.select_related('provider'),pk=int(data.get('model')),enabled=True,provider__enabled=True)
    context=data.get('context') or None
    if context:
        if not isinstance(context,dict) or context.get('kind') not in agent.LABELS or type(context.get('id'))!=int:
            raise ValidationError('引用资料无效。')
        if not agent.available(request.user,context['kind']).filter(pk=context['id']).exists(): raise PermissionDenied
    if not provider_key(model.provider) or not current_price(model): raise ValidationError('请让管理员先配置厂商密钥和模型价格。')
    created=False
    if conversation is None:
        conversation=AssistantConversation.objects.create(user=request.user,title=' '.join(history[-1]['content'].split())[:100])
        created=True
    try:
        job=agent.start(request.user,model,history,context,conversation)
    except Exception:
        if created: conversation.delete()
        raise
    return JsonResponse({'job':str(job.pk),'conversation':conversation.pk,'title':conversation.title},status=202)


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
                AssistantConversation.objects.filter(user=request.user).delete()
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
        AssistantJob.objects.filter(conversation_id=OuterRef('pk'),state='running',created_at__gt=timezone.now()-timezone.timedelta(minutes=5))))
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
            value.delete()
            return JsonResponse({'deleted':True})
        if data.get('action')!='rename': raise ValidationError('操作无效。')
        title=data.get('title')
        if not isinstance(title,str) or not title.strip() or len(title.strip())>100: raise ValidationError('名称需为 1–100 个字符。')
        value.title=title.strip(); value.save(update_fields=['title','updated_at'])
        return JsonResponse(conversation_row(value))
    if request.method!='GET': return JsonResponse({'error':'方法不支持。'},status=405)
    rows=[]; active=None
    for job in reversed(list(value.jobs.order_by('-created_at')[:100])):
        if job.user_text: rows.append({'role':'user','text':job.user_text})
        if job.state=='running': active=str(job.pk)
        elif job.result:
            rows.append({'role':'assistant','text':job.result.get('error') or job.result.get('text',''),'result':job.result})
    return JsonResponse({**conversation_row(value),'messages':rows,'active_job':active})


@team
@json_errors
def assistant_job(request,pk):
    job=get_object_or_404(AssistantJob,pk=pk,user=request.user)
    if request.method=='POST':
        AssistantJob.objects.filter(pk=job.pk,user=request.user,state='running').update(cancel_requested=True)
        return JsonResponse({'stopping':True})
    if request.method!='GET': return JsonResponse({'error':'方法不支持。'},status=405)
    if job.state=='running' and job.created_at<timezone.now()-timezone.timedelta(minutes=5):
        job.state='error'; job.result={'error':'服务已重启或本轮超时；已发生的调用可在 API 池查看。'}
        job.finished_at=timezone.now(); job.save(update_fields=['state','result','finished_at'])
    return JsonResponse({'state':job.state,'activity':job.activity,'result':job.result})


@team
@require_GET
@json_errors
def references(request):
    kind=request.GET.get('kind','task'); query=request.GET.get('q','')[:100]
    value=agent.run_tool(request.user,'search_workspace',{'kind':kind,'query':query})
    return JsonResponse(value)


@team
def manage(request):
    require_pool_owner(request)
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
                    notices.success(request,'厂商连接已保存。'); return redirect('api_manage')
            elif action=='model':
                instance=PoolModel.objects.filter(pk=request.POST.get('id')).first() if request.POST.get('id','').isdigit() else None
                model_form=ModelForm(request.POST,instance=instance)
                if model_form.is_valid():
                    with transaction.atomic():
                        value=model_form.save(); save_price(value,model_form.cleaned_data,value.price_source or '管理员登记')
                    notices.success(request,'模型与新价格版本已保存。'); return redirect('api_manage')
            elif action=='settings':
                settings_form=SettingsForm(request.POST,instance=pool_settings())
                if settings_form.is_valid(): settings_form.save(); notices.success(request,'团队额度已保存。'); return redirect('api_manage')
            elif action=='toggle_model':
                model=get_object_or_404(PoolModel,pk=int(request.POST.get('id')))
                model.enabled=not model.enabled; model.save(update_fields=['enabled'])
                return redirect('api_manage')
            elif action=='toggle_provider':
                provider=get_object_or_404(Provider,pk=int(request.POST.get('id')))
                provider.enabled=not provider.enabled; provider.save(update_fields=['enabled'])
                return redirect('api_manage')
            elif action=='reset_budget':
                scope='team' if request.POST.get('target')=='team' else 'user:'+str(get_object_or_404(User,pk=int(request.POST.get('user'))).pk)
                reset_budget(scope,request.POST.get('period','both'))
                notices.success(request,'额度已重置，历史费用和未完成调用的预留保留。')
                return redirect('api_manage')
            elif action=='grant_points':
                issue_points(request)
                return redirect('api_manage')
            elif action=='save_plan':
                save_plan(request)
                return redirect(reverse('api_pool')+'?scope=team')
            elif action=='reset_plans':
                reset_member_plans(); notices.success(request,'所有成员本周基础额度已重置，额外点数和历史费用保留。')
                return redirect(reverse('api_pool')+'?scope=team')
            elif action=='refresh':
                count=refresh_prices(force=True); notices.success(request,f'已处理 {count} 个模型的每日价格记录。'); return redirect('api_manage')
            elif action=='reconcile':
                call=get_object_or_404(Call,pk=request.POST.get('call'),status__in=['unknown','running'])
                if call.status=='running' and call.created_at>timezone.now()-timezone.timedelta(minutes=5): raise ValidationError('调用仍在执行，请稍后核对。')
                cost=Decimal(request.POST.get('cost',''))
                if not cost.is_finite() or cost<0 or cost>100000: raise ValidationError('核对金额无效。')
                settle(call,None,cost_override=cost)
                notices.success(request,'费用已核对并结算额度。'); return redirect('api_manage')
        elif request.GET.get('provider','').isdigit():
            provider_form=ProviderForm(instance=get_object_or_404(Provider,pk=request.GET['provider']))
        elif request.GET.get('model','').isdigit():
            value=get_object_or_404(PoolModel,pk=request.GET['model']); price=current_price(value)
            initial={field:getattr(price,field) for field in ('currency','input_rate','output_rate','cached_rate','cache_write_rate','cny_exchange_rate')} if price else {}
            model_form=ModelForm(instance=value,initial=initial)
    except (ValidationError,InvalidOperation,ValueError,TypeError,OverflowError) as exc:
        error=' '.join(exc.messages) if isinstance(exc,ValidationError) else '输入无效。'
    accounts=[]
    for user in User.objects.filter(is_active=True).order_by('username'):
        if perms.is_team_member(user): accounts.append({'user':user,'allowance':allowance(user),'budget':summary(user)})
    models=list(PoolModel.objects.select_related('provider').all())
    for model in models:
        model.current_price=current_price(model); model.has_price=model.current_price is not None
    providers=Provider.objects.filter(Q(enabled=True)|Q(models__isnull=False)).distinct()
    return render(request,'aihub/manage.html',{'provider_form':provider_form,'model_form':model_form,'settings_form':settings_form,
        'providers':[{'item':p,'has_key':bool(provider_key(p))} for p in providers],
        'provider_connections':[{'id':p.pk,'preset':discovery.preset_for(p),'name':p.name,'protocol':p.protocol,'base_url':p.base_url} for p in providers],
        'presets':discovery.PRESETS,
        'models':models,'accounts':accounts,'error':error,
        'pending_calls':Call.objects.filter(status__in=['unknown','running']).select_related('user','model__provider','price')[:50]})


def bearer(view):
    @wraps(view)
    def wrapper(request,*args,**kwargs):
        auth=request.headers.get('Authorization','')
        if not auth.startswith('Bearer '): return JsonResponse({'error':{'message':'需要成员调用凭证。','type':'authentication_error'}},status=401)
        digest=hashlib.sha256(auth[7:].strip().encode()).hexdigest()
        token=MemberToken.objects.select_related('user').filter(digest=digest,revoked_at__isnull=True).first()
        if not token: return JsonResponse({'error':{'message':'调用凭证无效或已撤销。','type':'authentication_error'}},status=401)
        try: require_member(token.user)
        except PermissionDenied: return JsonResponse({'error':{'message':'账户调用权限不可用。','type':'authentication_error'}},status=403)
        request.pool_user=token.user
        from .rate_limits import gate, RateLimited
        try:
            with gate(token.user, token):
                return view(request,*args,**kwargs)
        except RateLimited as error:
            response=JsonResponse({'error':{'message':str(error),'type':'rate_limit_error'}},status=429)
            response['Retry-After']='60'
            return response
        except OperationalError:
            response=JsonResponse({'error':{'message':'服务正忙，请稍后重试；已发生的用量仍以调用账目为准。','type':'server_busy'}},status=503)
            response['Retry-After']='2'
            return response
    return wrapper


@csrf_exempt
@bearer
@require_GET
@json_errors
def api_models(request):
    return JsonResponse({'object':'list','data':[{'id':m['alias'],'object':'model','owned_by':m['provider'],
        'native_model':m['model_id']} for m in model_catalog(request.pool_user) if m['configured']]})


@csrf_exempt
@bearer
@require_POST
@json_errors
def api_chat(request):
    data=json_body(request)
    supported={'model','messages','stream','tools','temperature','top_p','stop','max_tokens','max_completion_tokens','project_id','experiment_id'}
    if set(data)-supported: raise ValidationError('不支持的参数：'+', '.join(sorted(set(data)-supported)))
    if 'max_tokens' in data and 'max_completion_tokens' in data: raise ValidationError('输出上限参数只填一种。')
    if data.get('stream'): raise ValidationError('当前支持非流式文本调用，请设置 stream=false。')
    catalog=model_catalog(request.pool_user)
    matches=[m for m in catalog if data.get('model') in (m['alias'],m['model_id'])]
    if len(matches)!=1: raise ValidationError('模型不存在或存在同名，请使用 /models 返回的模型 ID。')
    model=PoolModel.objects.select_related('provider').get(pk=matches[0]['id'])
    history=data.get('messages')
    if not isinstance(history,list) or not 1<=len(history)<=80: raise ValidationError('messages 格式无效。')
    for row in history:
        if not isinstance(row,dict) or row.get('role') not in ('system','user','assistant','tool') or row.get('content') is not None and not isinstance(row['content'],str): raise ValidationError('当前只支持文本消息。')
        if any(str(k).startswith('_') for k in row): raise ValidationError('消息包含不支持的字段。')
        if len(str(row.get('content','')))>100000: raise ValidationError('消息过长。')
        if row['role']=='tool' and not isinstance(row.get('tool_call_id'),str): raise ValidationError('tool_call_id 无效。')
    tools=data.get('tools') or []
    if not isinstance(tools,list) or len(tools)>12: raise ValidationError('工具定义无效。')
    for tool in tools:
        f=tool.get('function') if isinstance(tool,dict) else None
        if not f or not isinstance(f.get('name'),str) or not isinstance(f.get('parameters'),dict): raise ValidationError('工具定义无效。')
        f.setdefault('description','')
    if tools and not model.supports_tools: raise ValidationError('该模型未启用工具调用。')
    options={}
    for name in ('temperature','top_p'):
        if name in data:
            v=data[name]
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or not 0<=v<=(2 if name=='temperature' else 1): raise ValidationError('采样参数无效。')
            options[name]=v
    if 'stop' in data:
        stop=[data['stop']] if isinstance(data['stop'],str) else data['stop']
        if not isinstance(stop,list) or len(stop)>4 or any(not isinstance(s,str) or len(s)>200 for s in stop): raise ValidationError('stop 参数无效。')
        options['stop']=stop
    limit=data.get('max_completion_tokens',data.get('max_tokens',model.max_output_tokens))
    if type(limit)!=int or not 1<=limit<=model.max_output_tokens: raise ValidationError('输出 token 上限无效。')
    project,experiment=context_objects(data.get('project_id'),data.get('experiment_id'))
    result=execute(request.pool_user,model,history,tools,limit,options,project=project,experiment=experiment)
    counts=result['counts']; message={'role':'assistant','content':result['text'] or None}
    if result['tool_calls']: message['tool_calls']=result['tool_calls']
    usage=None if counts is None else {'prompt_tokens':counts['input_tokens'],'completion_tokens':counts['output_tokens'],
        'total_tokens':counts['input_tokens']+counts['output_tokens'],'prompt_tokens_details':{'cached_tokens':counts['cached_tokens'],'cache_write_tokens':counts['cache_write_tokens']},
        'completion_tokens_details':{'reasoning_tokens':counts['reasoning_tokens']}}
    return JsonResponse({'id':result['call_id'],'object':'chat.completion','created':int(timezone.now().timestamp()),'model':matches[0]['alias'],
        'choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if result['tool_calls'] else 'stop'}],
        'usage':usage,'workbench':{'cost':result['cost'],'currency':result['currency'],'cost_cny':result['cost_cny'],
            'price_version':result['price_version'],'status':result['status']}})
