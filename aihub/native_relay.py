"""Native text APIs keep their wire formats and share the existing quota ledger."""
import json
import re
import time
from urllib.parse import quote
from django.http import JsonResponse,StreamingHttpResponse
from .channels import resolve_model
from .models import Call
from .network import json_request,json_events,TransportError
from .providers import normalize
from .relay import RelayError,read_body
from .routing import RoutePlan,can_fallback
from .service import provider_key,reserve,settle,keep_call_alive
from .timeouts import CONNECT_SECONDS,READ_SECONDS,STREAM_TOTAL_SECONDS
from .token_estimates import default_output

PROTOCOL={'responses':'openai','messages':'anthropic','gemini':'gemini','embeddings':'openai'}

def counts(kind,raw):
    usage=raw.get('usage') or {}
    if kind=='gemini':
        usage=raw.get('usageMetadata') or {}
        source=usage.get('promptTokenCount');total=usage.get('totalTokenCount')
        if type(source) is not int or type(total) is not int or total<source:return None
        output=total-source;cached=usage.get('cachedContentTokenCount',0);write=0;reasoning=usage.get('thoughtsTokenCount',0)
    elif kind=='messages':
        source=usage.get('input_tokens');cached=usage.get('cache_read_input_tokens',0);write=usage.get('cache_creation_input_tokens',0)
        if any(type(value) is not int for value in (source,cached,write)):return None
        source+=cached+write;output=usage.get('output_tokens');reasoning=0
    elif kind=='embeddings':
        source=usage.get('prompt_tokens',usage.get('total_tokens'));output=0;cached=0;write=0;reasoning=0
    else:
        source=usage.get('input_tokens');output=usage.get('output_tokens')
        detail=usage.get('input_tokens_details') or {};out=usage.get('output_tokens_details') or {}
        cached=detail.get('cached_tokens',0);write=detail.get('cache_write_tokens',0);reasoning=out.get('reasoning_tokens',0)
    result={'input_tokens':source,'output_tokens':output,'cached_tokens':cached,'cache_write_tokens':write,'reasoning_tokens':reasoning}
    if any(type(value) is not int or value<0 for value in result.values()) or cached+write>source:return None
    return result

def billing_payload(value):
    if isinstance(value,list):return [billing_payload(item) for item in value]
    if not isinstance(value,dict):return value
    if value.get('type') in ('input_image','image','image_url','input_file','document','input_audio') or 'inlineData' in value:
        return {'media_input':value.get('type','inlineData'),'conservative_tokens':32768}
    return {key:billing_payload(item) for key,item in value.items()}

def check_state(value,top=True):
    # Shared supplier credentials must not expose another user's stored objects.
    if isinstance(value,list):
        for item in value:check_state(item,False)
    elif isinstance(value,dict):
        if (value.get('file_id') and value.get('type') in ('file','input_file') or
                top and (value.get('conversation') or value.get('cachedContent'))):
            raise RelayError('此共享连接暂不接受未归属的上游文件、会话或缓存 ID；请传完整输入。','unowned_upstream_object')
        for key,item in value.items():
            if key not in ('tools','metadata'):check_state(item,False)

class Operation:
    def __init__(self,request,kind,model_name=None):
        self.request=request;self.kind=kind;self.body=read_body(request);self.token=request.pool_token
        if any(key in self.body for key in ('api_key','base_url','headers','endpoint')):
            raise RelayError('凭证和上游地址只能由团队管理员配置。')
        check_state(self.body)
        self.streaming=self.body.get('stream',False) if kind!='gemini' else bool(getattr(request,'native_stream',False))
        if type(self.streaming) is not bool:raise RelayError('stream 必须是布尔值。')
        tools=self.body.get('tools',[])
        from django.conf import settings
        if not isinstance(tools,list) or len(tools)>settings.WORKBENCH_RELAY_MAX_TOOLS:raise RelayError('工具定义过多或格式无效。')
        if kind=='messages' and (not isinstance(self.body.get('messages'),list) or not self.body['messages']):raise RelayError('需要 messages。')
        if kind=='responses' and not isinstance(self.body.get('input'),(str,list)):raise RelayError('input 应为文本或输入项列表。')
        if kind=='gemini' and (not isinstance(self.body.get('contents'),list) or not self.body['contents']):raise RelayError('需要 contents。')
        if kind=='embeddings' and not isinstance(self.body.get('input'),(str,list)):raise RelayError('需要有效的 input。')
        field={'responses':'max_output_tokens','messages':'max_tokens','gemini':'maxOutputTokens','embeddings':None}[kind]
        generation=self.body.get('generationConfig',{}) if kind=='gemini' else self.body
        if not isinstance(generation,dict):raise RelayError('generationConfig 无效。')
        limit=generation.get(field) if field else 0
        self.model=resolve_model(request.pool_user,model_name or self.body.get('model'),self.token,protocol=PROTOCOL[kind],limit=limit)
        self.limit=(default_output(self.model) if limit is None else limit)
        if type(self.limit) is not int or self.limit<0 or self.limit>self.model.max_output_tokens or field and self.limit==0:
            raise RelayError('输出上限超出模型配置。')
        if field:generation[field]=self.limit
        if kind=='gemini':self.body['generationConfig']=generation
        self.previous=None
        previous=self.body.get('previous_response_id')
        if previous:
            self.previous=Call.objects.filter(api_token=self.token,api_kind='responses',provider_request_id=previous).select_related('model__provider').first()
            if not self.previous or (self.previous.model.pk!=self.model.pk and
                not (self.model.public_alias and self.previous.model.public_alias==self.model.public_alias)):
                raise RelayError('previous_response_id 不属于这个 Key 的当前连接。','unowned_response',403)
            from .relay import check_token
            check_token(self.token,self.previous.model)
            if not self.previous.model.enabled or not self.previous.model.provider.enabled:raise RelayError('原会话连接已停用。','model_unavailable',503)
            self.model=self.previous.model
            if self.previous.provider_endpoint and self.previous.provider_endpoint!=self.model.provider.base_url:
                raise RelayError('原响应的连接地址已更改，不能自动续接。','connection_changed',409)
            if self.limit>self.model.max_output_tokens:raise RelayError('原会话连接不支持此输出上限。')
        # Apply the same project binding rules as Chat Completions.
        from .views import independent_context
        project_id=self.body.pop('project_id',None);experiment_id=self.body.pop('experiment_id',None)
        for field_name,bound,id_value,current in [('project',self.token.project_bound,self.token.project_id,project_id),
                                                ('experiment',self.token.experiment_bound,self.token.experiment_id,experiment_id)]:
            if bound and (id_value is None or current is not None and (type(current) is not int or current!=id_value)):
                raise RelayError('请求与 Key 绑定的项目或实验不一致。','permission_denied',403)
        self.project,self.experiment=independent_context(request.pool_user,self.token.experiment_id if self.token.experiment_bound else experiment_id,
                                                       self.token.project_id if self.token.project_bound else project_id)
        self.plan=RoutePlan(self.model,self.token,[],self.limit)
        if self.previous:self.plan.identifiers=[self.model.pk]
        self.call=None;self.began=time.monotonic();self.settled=False;self.started=False;self.emitted=False

    def connection(self,model):
        secret=provider_key(model.provider);headers={'Content-Type':'application/json'}
        if self.kind=='messages':
            headers.update({'x-api-key':secret,'anthropic-version':'2023-06-01'})
            beta=self.request.headers.get('anthropic-beta','')
            if beta and re.fullmatch(r'[a-zA-Z0-9,._-]{1,4096}',beta):headers['anthropic-beta']=beta
        elif self.kind=='gemini':headers['x-goog-api-key']=secret
        else:headers['Authorization']='Bearer '+secret
        if self.kind=='gemini':
            endpoint='/models/'+quote(model.model_id.removeprefix('models/'),safe='')+(':streamGenerateContent?alt=sse' if self.streaming else ':generateContent')
        else:endpoint='/'+self.kind
        body=dict(self.body)
        if self.kind!='gemini':body['model']=model.model_id
        return model.provider.base_url.rstrip('/')+endpoint,headers,body

    def admit(self):
        self.call=None;self.settled=False;self.started=False
        try:
            model=self.plan.next_model();url,headers,body=self.connection(model)
            estimate=billing_payload(body)
            previous_tokens=((self.previous.input_tokens if self.previous.input_tokens is not None else self.previous.estimated_input_tokens)
                             +(self.previous.output_tokens if self.previous.output_tokens is not None else self.limit)) if self.previous else 0
            self.call=reserve(self.request.pool_user,model,[{'role':'user','content':'','_billing_payload':estimate,'_prior_tokens':previous_tokens}],[],self.limit,'api',
                              None,self.project,self.experiment,api_token=self.token)
            Call.objects.filter(pk=self.call.pk).update(api_kind=self.kind,request_bytes=len(self.request.body))
            self.plan.reserved(self.call)
            return url,headers,body
        except Exception:
            if self.call and not self.settled:self.finish(error=TransportError('execution_checkpoint_failed',False))
            self.plan.complete();raise

    def finish(self,raw=None,error=None):
        if self.settled:return
        usage=counts(self.kind,raw) if raw else None
        uncertain=bool(error and (error.uncertain or self.emitted))
        code=error.code if error else ''
        status='unknown' if uncertain else 'failed' if error else 'success'
        if raw and raw.get('status') in ('queued','in_progress'):status='unknown';code='usage_pending'
        if raw and raw.get('status') in ('failed','cancelled'):
            status='success' if usage else 'unknown';code='upstream_response_'+raw['status']
        Call.objects.filter(pk=self.call.pk).update(latency_ms=int((time.monotonic()-self.began)*1000),
            provider_request_id=str((raw or {}).get('id') or (raw or {}).get('responseId') or self.call.provider_request_id)[:200])
        settle(self.call,usage,status,code);self.settled=True;self.call.refresh_from_db();self.plan.complete(self.call)

    def run(self):
        while True:
            try:
                url,headers,body=self.admit()
                with keep_call_alive(self.call):
                    self.started=True
                    raw=json_request(url,headers,body,timeout=READ_SECONDS,connect_timeout=CONNECT_SECONDS)
                if raw.get('error') and raw.get('status')!='failed':raise TransportError('upstream_response_error',True)
                self.finish(raw)
                result=JsonResponse(raw);result['X-Request-ID']=self.plan.request_id;result['x-should-retry']='false'
                return result
            except TransportError as error:
                self.finish(error=error)
                if can_fallback(self.call) and self.plan.position<len(self.plan.identifiers):continue
                raise RelayError('上游调用未完成（'+error.code+'），请按调用编号查询账目。',
                    'upstream_result_unknown' if self.call.status=='unknown' else 'upstream_error',502,call_id=self.plan.request_id) from None
            except Exception:
                if self.call and not self.settled:self.finish(error=TransportError('unexpected_response',self.started))
                self.plan.complete()
                if self.started:raise RelayError('上游响应无法处理，请按调用编号查询账目。','upstream_result_unknown',502,call_id=self.plan.request_id) from None
                raise

    def frames(self,connection):
        source=None;final=None;usage={};identifier='';stopped=False
        try:
            url,headers,body=connection
            with keep_call_alive(self.call):
                self.started=True
                source=json_events(url,headers,body,timeout=READ_SECONDS,connect_timeout=CONNECT_SECONDS,
                                   total_timeout=STREAM_TOTAL_SECONDS,allow_query=self.kind=='gemini')
                for event in source:
                    kind=event.get('type','')
                    if event.get('error') or kind=='error':raise TransportError('upstream_stream_error',True)
                    if self.kind=='responses':
                        response=event.get('response') or {}
                        if response.get('id'):
                            identifier=response['id'];Call.objects.filter(pk=self.call.pk).update(provider_request_id=identifier[:200]);self.call.provider_request_id=identifier[:200]
                        if kind in ('response.completed','response.incomplete','response.failed'):final=response;stopped=True
                    elif self.kind=='messages':
                        if kind=='message_start':
                            message=event.get('message') or {};identifier=message.get('id','');usage.update(message.get('usage') or {})
                        if kind=='message_delta':usage.update(event.get('usage') or {})
                        if kind=='message_stop':stopped=True;final={'id':identifier,'content':[],'usage':usage}
                    else:
                        if event.get('usageMetadata'):usage.update(event['usageMetadata'])
                        identifier=event.get('responseId') or identifier
                        if any(candidate.get('finishReason') for candidate in event.get('candidates',[])):stopped=True
                        final={'responseId':identifier,'candidates':[],'usageMetadata':usage}
                    if identifier and identifier!=self.call.provider_request_id:
                        self.call.provider_request_id=identifier[:200]
                        Call.objects.filter(pk=self.call.pk).update(provider_request_id=identifier[:200])
                    if self.call.first_token_ms is None and (event.get('delta') or kind.endswith('.delta') or self.kind=='gemini' and event.get('candidates')):
                        self.call.first_token_ms=int((time.monotonic()-self.began)*1000)
                        Call.objects.filter(pk=self.call.pk,first_token_ms__isnull=True).update(first_token_ms=self.call.first_token_ms)
                    self.emitted=True
                    yield (('event: '+kind+'\n') if kind else '')+'data: '+json.dumps(event,ensure_ascii=False,separators=(',',':'))+'\n\n'
                if not stopped:raise TransportError('incomplete_stream',True)
                self.finish(final)
        finally:
            close=getattr(source,'close',None)
            if close:close()

    def error_event(self,code):
        value=({'type':'error','code':code,'message':code,'param':None} if self.kind=='responses' else
               {'type':'error','error':{'type':'api_error','message':code}} if self.kind=='messages' else
               {'error':{'code':502,'message':code,'status':'UNAVAILABLE'}})
        value['workbench']={'call_id':self.plan.request_id,'status':self.call.status if self.call else 'failed'}
        return 'event: error\ndata: '+json.dumps(value)+'\n\n'

    def events(self):
        try:
            while True:
                try:
                    yield from self.frames(self.admitted)
                    return
                except TransportError as error:
                    if self.call:self.finish(error=error)
                    if self.call and not self.emitted and can_fallback(self.call) and self.plan.position<len(self.plan.identifiers):
                        self.admitted=self.admit();continue
                    yield self.error_event(error.code);return
                except GeneratorExit:raise
                except Exception:
                    if self.call:self.finish(error=TransportError('unexpected_response',self.started))
                    yield self.error_event('upstream_result_unknown');return
        finally:
            if self.call and not self.settled:self.finish(error=TransportError('stream_disconnected',self.started))
            self.plan.complete()

def respond(request,kind,model_name=None):
    operation=Operation(request,kind,model_name)
    if not operation.streaming:return operation.run()
    operation.admitted=operation.admit()
    response=StreamingHttpResponse(operation.events(),content_type='text/event-stream; charset=utf-8')
    response['Cache-Control']='no-cache, no-store';response['X-Accel-Buffering']='no';response['x-should-retry']='false'
    response['X-Request-ID']=operation.plan.request_id
    return response
