"""Bounded operational summaries and supplier-confirmed reconciliation."""
from decimal import Decimal,InvalidOperation
from urllib.parse import urlsplit,quote
from django.utils import timezone
from .models import Call,Provider,DailyPrice
from .service import settle,provider_key
from .network import json_request,TransportError

def dashboard():
    first=timezone.now()-timezone.timedelta(days=7)
    rows=list(Call.objects.filter(created_at__gte=first).order_by('-created_at').values(
        'model__provider_id','status','error_code','latency_ms','first_token_ms')[:1000])
    def percentile(values):
        values=sorted(value for value in values if value is not None)
        return values[min(len(values)-1,int((len(values)-1)*.95))] if values else None
    result=[]
    for provider in Provider.objects.order_by('name'):
        own=[row for row in rows if row['model__provider_id']==provider.pk]
        complete=[row for row in own if row['status']!='running']
        successful=sum(row['status']=='success' and not row['error_code'] for row in complete)
        result.append({'name':provider.name,'calls':len(own),'success_pct':round(successful/len(complete)*100,1) if complete else None,
                       'p95_ms':percentile([row['latency_ms'] for row in complete]),
                       'first_token_p95_ms':percentile([row['first_token_ms'] for row in complete]),
                       'unknown':sum(row['status']=='unknown' for row in own)})
    stale=DailyPrice.objects.filter(day=timezone.localdate(),status='failed',model__enabled=True,model__provider__enabled=True).count()
    return {'channels':result,'sample_size':len(rows),'pending':Call.objects.filter(status='unknown').count(),'price_failures':stale}

def reconcile(limit=50,timeout=15):
    checked=0;settled=0
    for call in Call.objects.filter(status='unknown',provider_request_id__gt='').select_related('model__provider','price')[:limit]:
        provider=call.model.provider;host=urlsplit(provider.base_url).hostname
        if call.provider_endpoint and call.provider_endpoint!=provider.base_url:continue
        try:
            if call.api_kind=='responses' and provider.protocol=='openai':
                raw=json_request(provider.base_url.rstrip('/')+'/responses/'+quote(call.provider_request_id,safe=''),
                    {'Authorization':'Bearer '+provider_key(provider)},timeout=timeout)
                checked+=1
                if raw.get('id')!=call.provider_request_id or raw.get('status') not in ('completed','incomplete','failed','cancelled'):continue
                from .native_relay import counts
                usage=counts('responses',raw)
                if not usage:continue
                settle(call,usage,error_code='upstream_response_'+raw['status'] if raw['status'] in ('failed','cancelled') else '');settled+=1
            elif host=='openrouter.ai':
                raw=json_request(provider.base_url.rstrip('/')+'/generation?id='+quote(call.provider_request_id,safe=''),
                    {'Authorization':'Bearer '+provider_key(provider)},timeout=timeout,allow_query=True)
                checked+=1;data=raw.get('data') or {}
                if data.get('id')!=call.provider_request_id or call.price.currency!='USD':continue
                cost=Decimal(str(data.get('total_cost')))
                if not cost.is_finite() or not 0<=cost<=100000:continue
                settle(call,None,cost_override=cost);settled+=1
        except (TransportError,InvalidOperation,ValueError,TypeError):continue
    return {'checked':checked,'settled':settled}
