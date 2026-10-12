"""Native endpoint adapters; normal browser sessions never grant relay access."""
from urllib.parse import quote
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST,require_http_methods,require_GET
from .views import bearer,relay_errors
from .native_relay import respond,counts,PROTOCOL
from .relay import RelayError,read_body,check_token
from .channels import resolve_model,public_name
from .models import Call,PoolModel
from .network import json_request,TransportError
from .service import provider_key,settle

@csrf_exempt
@bearer
@require_POST
@relay_errors
def responses(request):return respond(request,'responses')

@csrf_exempt
@bearer
@require_POST
@relay_errors
def messages(request):return respond(request,'messages')

@csrf_exempt
@bearer
@require_POST
@relay_errors
def embeddings(request):return respond(request,'embeddings')

@csrf_exempt
@bearer
@require_POST
@relay_errors
def gemini(request,model_name,streaming=False):
    request.native_stream=streaming
    return respond(request,'gemini',model_name)

@csrf_exempt
@bearer
@require_GET
@relay_errors
def gemini_models(request):
    token=request.pool_token
    from .prices import current_price
    models=PoolModel.objects.filter(enabled=True,provider__enabled=True,provider__protocol='gemini').select_related('provider')
    if token.allowed_models:models=models.filter(pk__in=token.allowed_models)
    rows={public_name(model):{'name':'models/'+public_name(model),'displayName':str(model),
            'outputTokenLimit':model.max_output_tokens,'supportedGenerationMethods':['generateContent','streamGenerateContent','countTokens']}
          for model in models if current_price(model) is not None and provider_key(model.provider)}
    return JsonResponse({'models':list(rows.values())})

@csrf_exempt
@bearer
@require_http_methods(['GET','DELETE'])
@relay_errors
def stored_response(request,response_id):
    call=Call.objects.filter(api_token=request.pool_token,api_kind='responses',provider_request_id=response_id).select_related('model__provider','price').first()
    if call is None:raise RelayError('响应不存在或不属于这个 Key。','not_found',404)
    if call.provider_endpoint and call.provider_endpoint!=call.model.provider.base_url:
        raise RelayError('原响应连接已更改，请由管理员核对原连接账目。','connection_changed',409)
    check_token(request.pool_token,call.model)
    url=call.model.provider.base_url.rstrip('/')+'/responses/'+quote(response_id,safe='')
    try:raw=json_request(url,{'Authorization':'Bearer '+provider_key(call.model.provider)},timeout=30,method=request.method)
    except TransportError as error:raise RelayError('上游响应暂不可读取。','upstream_error',502,call_id=str(call.pk)) from None
    if request.method=='GET' and call.status=='unknown' and raw.get('status') in ('completed','incomplete','failed','cancelled'):
        usage=counts('responses',raw)
        if usage:settle(call,usage,error_code='upstream_response_'+raw['status'] if raw['status'] in ('failed','cancelled') else '')
    response=JsonResponse(raw);response['Cache-Control']='no-store';response['X-Request-ID']=str(call.pk)
    return response

@csrf_exempt
@bearer
@require_POST
@relay_errors
def count_input(request,kind,model_name=None):
    body=read_body(request)
    if any(key in body for key in ('api_key','base_url','headers','endpoint')):raise RelayError('凭证与上游地址只能由管理员配置。')
    from .native_relay import check_state
    check_state(body)
    model=resolve_model(request.pool_user,model_name or body.get('model'),request.pool_token,protocol=PROTOCOL[kind])
    secret=provider_key(model.provider)
    if kind=='gemini':
        headers={'x-goog-api-key':secret};endpoint='/models/'+quote(model.model_id.removeprefix('models/'),safe='')+':countTokens'
        body.pop('model',None)
    else:
        endpoint='/'+kind+('/input_tokens' if kind=='responses' else '/count_tokens');body['model']=model.model_id
        headers={'Authorization':'Bearer '+secret} if kind=='responses' else {'x-api-key':secret,'anthropic-version':'2023-06-01'}
    try:raw=json_request(model.provider.base_url.rstrip('/')+endpoint,headers,body,timeout=30)
    except TransportError:raise RelayError('该连接的 token 计数接口不可用。','upstream_error',502) from None
    return JsonResponse(raw)
