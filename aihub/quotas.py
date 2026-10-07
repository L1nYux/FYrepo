"""Read vendor quota without inference. Only fixed official hosts receive saved keys.

Contracts: MiniMax's official cli/src/{client/endpoints,types/api,utils/quota}.ts;
ZCode's official packages/services/src/usage-stats/providers/bigmodelUsageQuota*.ts.
Account balance and plan quota are distinct from our local team spending meter.
"""
import hashlib
import math
from datetime import timezone as utc_timezone
from urllib.parse import urlsplit
from django.core.cache import cache
from django.utils import timezone
from .network import json_request, TransportError
from .service import provider_key
from .models import Provider

MINIMAX_HOSTS={'api.minimaxi.com','api.minimax.cn','api.minimax.io'}
QWEN_HOSTS={'dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com','coding.dashscope.aliyuncs.com'}

def number(value):
    if isinstance(value,bool) or value is None:return None
    try:
        result=float(value)
        return result if math.isfinite(result) and 0<=result<=1e18 else None
    except (ValueError,TypeError,OverflowError):return None

def stamp(value):
    result=number(value)
    if not result:return None
    if result>1e11:result/=1000
    try:return timezone.datetime.fromtimestamp(result,utc_timezone.utc).isoformat()
    except (ValueError,OverflowError,OSError):return None

def configuration(provider,key):
    host=urlsplit(provider.base_url).hostname
    fingerprint=hashlib.sha256((provider.base_url+'\0'+provider.quota_kind+'\0'+key).encode()).hexdigest()
    result={'fingerprint':fingerprint,'supported':False,'kind':'account','console_url':'','note':'该厂商尚未提供已接入的余额查询。'}
    if host in MINIMAX_HOSTS:
        kind=provider.quota_kind
        if kind=='auto':kind='account' if key.startswith('sk-api-') else 'plan'
        result.update(supported=True,kind=kind,console_url='https://platform.minimaxi.com' if host!='api.minimax.io' else 'https://platform.minimax.io',
            endpoint=('https://api.minimax.io' if host=='api.minimax.io' else 'https://api.minimaxi.com')+('/account/query_balance' if kind=='account' else '/v1/token_plan/remains'),note='厂商账户共享余额' if kind=='account' else 'M Plan 套餐额度，各工具共享；不等同于现金余额。',vendor='minimax')
    elif host=='open.bigmodel.cn':
        plan=provider.quota_kind=='plan' or (provider.quota_kind=='auto' and '/coding/' in urlsplit(provider.base_url).path)
        result.update(kind='plan' if plan else 'account',console_url='https://bigmodel.cn/finance-center/resource-package/package-management',note='套餐额度' if plan else '普通 API Key 的现金余额暂需在智谱后台查看。',vendor='zhipu')
        if plan:result.update(supported=True,endpoint='https://bigmodel.cn/api/monitor/usage/quota/limit')
    elif host in QWEN_HOSTS:
        result.update(console_url='https://bailian.console.aliyun.com/',kind='plan' if provider.quota_kind=='plan' or host.startswith('coding.') else 'account',note='千问套餐用量需在百炼后台查看；阿里云账户余额查询需要费用访问凭证，模型 API Key 无法代替。')
    return result

def snapshot(provider):
    key=provider_key(provider);config=configuration(provider,key)
    old=provider.quota_snapshot if isinstance(provider.quota_snapshot,dict) else {}
    value=old.get('value') if old.get('fingerprint')==config['fingerprint'] else None
    return {**{k:config[k] for k in ('supported','kind','console_url','note')},'value':value,'error':'','stale':bool(value)}

def minimax(data,kind):
    if data.get('base_resp',{}).get('status_code',0)!=0:raise ValueError('rejected')
    if kind=='account':
        amount=number(data.get('available_amount'))
        if amount is None:raise ValueError('balance missing')
        return {'balance':amount,'windows':[]}
    windows=[]
    rows=data.get('model_remains')
    if not isinstance(rows,list):raise ValueError('quota missing')
    for row in rows[:20]:
        if not isinstance(row,dict):continue
        name=str(row.get('model_name','套餐'))[:80]
        for prefix,label,end in [('current_interval','5 小时窗口','end_time'),('current_weekly','周窗口','weekly_end_time')]:
            total=number(row.get(prefix+'_total_count'));count=number(row.get(prefix+'_usage_count'));percent=number(row.get(prefix+'_remaining_percent'));status=row.get(prefix+'_status')
            remaining=None
            if total and count is not None and count<=total:
                remaining=count
                if percent is not None:
                    distances=[abs(count/total*100-percent),abs((total-count)/total*100-percent)]
                    if min(distances)>1:remaining=None
                    elif distances[1]<distances[0]:remaining=total-count
            if status==2:remaining=0;percent=0
            if status==3:remaining=None;percent=None
            if remaining is None and percent is None and status!=3:continue
            windows.append({'label':name+' · '+label,'remaining':remaining,'total':total,'remaining_percent':percent,'reset_at':stamp(row.get(end)),'unlimited':status==3})
    if not windows:raise ValueError('unrecognized quota')
    return {'windows':windows}

def zhipu(data):
    if data.get('success') is False or data.get('code') not in (None,0,200):raise ValueError('rejected')
    rows=data.get('data',{}).get('limits');windows=[]
    if not isinstance(rows,list):raise ValueError('quota missing')
    for row in rows[:20]:
        if not isinstance(row,dict):continue
        remaining=number(row.get('remaining'));used=number(row.get('currentValue'));total=number(row.get('usage'));percent=number(row.get('percentage'))
        if remaining is None and total is not None and used is not None:remaining=max(0,total-used)
        if remaining is None and percent is None:continue
        kind=str(row.get('type','配额'))[:80]
        windows.append({'label':{'TOKENS_LIMIT':'Token 配额','TIME_LIMIT':'调用配额'}.get(kind,kind),'remaining':remaining,'total':total,'remaining_percent':max(0,100-percent) if percent is not None and percent<=100 else None,'reset_at':stamp(row.get('nextResetTime')),'unlimited':False})
    if not windows:raise ValueError('no quota')
    return {'windows':windows}

def refresh(provider):
    key=provider_key(provider);config=configuration(provider,key);result=snapshot(provider)
    if not config['supported']:return result
    if not key:return {**result,'error':'尚未配置 API Key。'}
    # Limit manual refreshes and prevent concurrent duplicate requests. Keys never enter cache names.
    lock='vendor-quota:'+str(provider.pk)+':'+config['fingerprint']
    if not cache.add(lock,True,15):return {**result,'error':'请稍后再刷新。'}
    try:
        headers={'Authorization':key if config.get('vendor')=='zhipu' else 'Bearer '+key}
        data=json_request(config['endpoint'],headers,timeout=12)
        value=zhipu(data) if config.get('vendor')=='zhipu' else minimax(data,config['kind'])
        if 'balance' in value:value['currency']='USD' if urlsplit(provider.base_url).hostname=='api.minimax.io' else 'CNY'
        value['updated_at']=timezone.now().isoformat()
        # Discard late results if the connection or key changed while the request ran.
        current=Provider.objects.get(pk=provider.pk)
        if configuration(current,provider_key(current))['fingerprint']!=config['fingerprint']:
            return {**snapshot(current),'error':'连接已更新，请重新刷新。'}
        Provider.objects.filter(pk=provider.pk).update(quota_snapshot={'fingerprint':config['fingerprint'],'value':value})
        return {**result,'value':value,'stale':False}
    except (TransportError,ValueError,TypeError,AttributeError) as error:
        reason='认证未通过，请确认 Key 与额度类型。' if getattr(error,'code','') in ('http_401','http_403') else '厂商额度暂时无法读取，请在官方后台核对。'
        return {**result,'error':reason}
