"""OpenAI-compatible streams with the same quota reservation and settlement as chat."""
import json
import time
from django.utils import timezone
from .models import Call
from .network import TransportError, json_events
from .providers import native_payload, normalize, compatible_finish_reason
from .timeouts import CONNECT_SECONDS, READ_SECONDS, STREAM_TOTAL_SECONDS
from .service import reserve, settle, provider_key


def usage(counts):
    if counts is None: return None
    return {'prompt_tokens':counts['input_tokens'],'completion_tokens':counts['output_tokens'],
        'total_tokens':counts['input_tokens']+counts['output_tokens'],
        'prompt_tokens_details':{'cached_tokens':counts['cached_tokens'],'cache_write_tokens':counts['cache_write_tokens']},
        'completion_tokens_details':{'reasoning_tokens':counts['reasoning_tokens']}}


class ScopedStream:
    """Django consumes WSGI responses after request-local tenancy has been restored."""
    def __init__(self, iterator, token, lease):
        self.iterator=iter(iterator); self.token=token; self.lease=lease; self.closed=False

    def __iter__(self): return self

    def __next__(self):
        from core.tenancy import scope
        from core.workspace_audit import acting_as
        with scope(self.token.workspace), acting_as(self.token.user):
            try: return next(self.iterator)
            except StopIteration:
                self.close(); raise

    def close(self):
        if self.closed: return
        self.closed=True
        from core.tenancy import scope
        from core.workspace_audit import acting_as
        with scope(self.token.workspace), acting_as(self.token.user):
            try:
                close=getattr(self.iterator,'close',None)
                if close: close()
            finally: self.lease.__exit__(None,None,None)


class ChatStream:
    def __init__(self, user, model, messages, tools, limit, options, alias, include_usage, project=None, experiment=None, api_token=None):
        self.call=reserve(user,model,messages,tools,limit,'api',None,project,experiment,api_token=api_token)
        self.model=model; self.messages=messages; self.tools=tools; self.limit=limit; self.options=options
        self.alias=alias; self.include_usage=include_usage; self.created=int(timezone.now().timestamp())
        self.started=False; self.settled=False; self.closed=False; self.emitted=False; self.began=time.monotonic()
        self.iterator=self.events()

    def __iter__(self): return self
    def __next__(self): return next(self.iterator)

    def frame(self, delta=None, finish=None, **extra):
        if delta:
            self.emitted=True
            if any(delta.get(key) for key in ('content','reasoning_content','tool_calls')) and self.call.first_token_ms is None:
                self.call.first_token_ms=int((time.monotonic()-self.began)*1000)
                Call.objects.filter(pk=self.call.pk,first_token_ms__isnull=True).update(first_token_ms=self.call.first_token_ms)
        value={'id':str(self.call.pk),'object':'chat.completion.chunk','created':self.created,'model':self.alias,
            'choices':[] if delta is None else [{'index':0,'delta':delta,'finish_reason':finish}],**extra}
        return 'data: '+json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n\n'

    def finish(self, result=None, status='unknown', code='stream_disconnected'):
        if self.settled: return
        Call.objects.filter(pk=self.call.pk).update(latency_ms=int((time.monotonic()-self.began)*1000),provider_request_id=(result or {}).get('id',''))
        settle(self.call,(result or {}).get('counts'),status,code)
        self.settled=True

    def events(self):
        upstream=None
        from .service import keep_call_alive
        heartbeat=keep_call_alive(self.call)
        heartbeat.__enter__()
        try:
            if self.model.provider.protocol!='openai':
                from .native_streams import stream
                self.started=True
                result=None
                upstream=stream(self.model,provider_key(self.model.provider),self.messages,self.tools,self.limit,self.options)
                for item in upstream:
                    if 'delta' in item:yield self.frame(item['delta'])
                    if 'result' in item:result=item['result']
                if result is None:raise TransportError('incomplete_stream',True)
                self.finish(result,'success','')
            else:
                endpoint,body=native_payload(self.model,self.messages,self.tools,self.limit,self.options)
                body['stream']=True
                from urllib.parse import urlsplit
                host=urlsplit(self.model.provider.base_url).hostname or ''
                if not (host=='bigmodel.cn' or host.endswith('.bigmodel.cn')): body['stream_options']={'include_usage':True}
                headers={'Content-Type':'application/json','Authorization':'Bearer '+provider_key(self.model.provider)}
                raw_usage=None; request_id=''; content=''; calls={}; reasoning=''; finish=None
                upstream=json_events(self.model.provider.base_url.rstrip('/')+endpoint,headers,body,
                    timeout=READ_SECONDS,connect_timeout=CONNECT_SECONDS,total_timeout=STREAM_TOTAL_SECONDS)
                self.started=True
                for chunk in upstream:
                    if chunk.get('error'): raise TransportError('upstream_stream_error',True)
                    request_id=str(chunk.get('id') or request_id)[:200]
                    if chunk.get('usage') is not None: raw_usage=chunk['usage']
                    choices=chunk.get('choices') or []
                    if not choices: continue
                    choice=choices[0]
                    if 'message' in choice:
                        result=normalize(self.model,chunk)
                        self.finish(result,'success','')
                        delta={'role':'assistant','content':result['text']}
                        if result.get('reasoning'): delta['reasoning_content']=result['reasoning']
                        if result['tool_calls']: delta['tool_calls']=[{'index':i,**c} for i,c in enumerate(result['tool_calls'])]
                        yield self.frame(delta)
                        break
                    delta=choice.get('delta') or {}
                    part=delta.get('content') or ''
                    if not isinstance(part,str): raise TransportError('invalid_response',True)
                    content+=part
                    thought=delta.get('reasoning_content') or delta.get('reasoning') or ''
                    if isinstance(thought,str): reasoning+=thought
                    for item in delta.get('tool_calls') or []:
                        index=item.get('index',0)
                        if type(index)!=int or not 0<=index<=31: raise TransportError('invalid_response',True)
                        call=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                        if item.get('id'): call['id']=item['id']
                        for key in ('name','arguments'):
                            value=(item.get('function') or {}).get(key) or ''
                            if not isinstance(value,str): raise TransportError('invalid_response',True)
                            call['function'][key]+=value
                    if choice.get('finish_reason') is not None: finish=choice['finish_reason']
                    if delta: yield self.frame(delta)
                else:
                    if finish is None: raise TransportError('incomplete_stream',True)
                    result=normalize(self.model,{'id':request_id,'choices':[{'message':{'role':'assistant','content':content,
                        'reasoning_content':reasoning,'tool_calls':[calls[k] for k in sorted(calls)]},'finish_reason':finish}],'usage':raw_usage})
                    self.finish(result,'success','')
            self.call.refresh_from_db()
            yield self.frame({},compatible_finish_reason(result))
            if self.include_usage:
                yield self.frame(usage=usage(result['counts']),workbench={'call_id':str(self.call.pk),'status':self.call.status,
                    'cost_cny':str(self.call.cost_cny) if self.call.cost_cny is not None else None,'price_version':self.call.price_id})
            yield 'data: [DONE]\n\n'
        except TransportError as error:
            uncertain=error.uncertain or self.emitted
            self.finish(status='unknown' if uncertain else 'failed',code=error.code)
            yield 'data: '+json.dumps({'error':{'message':'上游调用未完成。','type':error.code},'workbench':{'call_id':str(self.call.pk),'status':'unknown' if uncertain else 'failed'}},ensure_ascii=False)+'\n\n'
            yield 'data: [DONE]\n\n'
        except GeneratorExit: raise
        except Exception:
            self.finish(code='unexpected_stream_response')
            yield 'data: '+json.dumps({'error':{'message':'上游响应无法处理，费用待核对。','type':'server_error'},'workbench':{'call_id':str(self.call.pk)}} ,ensure_ascii=False)+'\n\n'
            yield 'data: [DONE]\n\n'
        finally:
            if upstream is not None: upstream.close()
            heartbeat.__exit__(None,None,None)
            if not self.settled: self.finish(status='unknown' if self.started else 'failed',code='stream_disconnected' if self.started else 'stream_not_started')

    def close(self):
        if self.closed: return
        self.closed=True
        self.iterator.close()
        # Closing a generator before its first next() does not execute its finally block.
        if not self.settled: self.finish(status='unknown' if self.started else 'failed',code='stream_disconnected' if self.started else 'stream_not_started')


class RoutedChatStream:
    """Keep one public stream ID across at most two explicitly configured routes."""
    def __init__(self, user, model, messages, tools, limit, options, alias, include_usage,
                 project=None, experiment=None, api_token=None):
        from .routing import RoutePlan
        self.plan=RoutePlan(model,api_token,tools,limit,messages=messages)
        self.arguments=(user,messages,tools,limit,options,alias,include_usage,project,experiment,api_token)
        self.inner=None; self.closed=False
        self.start()
        self.call=self.inner.call
        self.iterator=self.events()

    def start(self):
        selected=self.plan.next_model()
        user,messages,tools,limit,options,alias,include_usage,project,experiment,token=self.arguments
        self.inner=None
        try:
            self.inner=ChatStream(user,selected,messages,tools,limit,options,alias,include_usage,
                project,experiment,api_token=token)
            self.plan.reserved(self.inner.call)
        except Exception:
            if self.inner is not None: self.inner.close()
            self.plan.complete()
            raise

    def __iter__(self): return self
    def __next__(self): return next(self.iterator)

    def rewrite(self, frame):
        if frame.strip()=='data: [DONE]': return frame
        value=json.loads(frame[6:])
        if 'id' in value: value['id']=self.plan.request_id
        if 'workbench' in value: value['workbench'].update(self.plan.details(self.inner.call))
        return 'data: '+json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n\n'

    def events(self):
        from .routing import can_fallback
        emitted=False
        try:
            while True:
                retry=False
                for frame in self.inner:
                    value=None if frame.strip()=='data: [DONE]' else json.loads(frame[6:])
                    if value and 'error' in value:
                        self.inner.close()
                        self.inner.call.refresh_from_db()
                        self.plan.complete(self.inner.call)
                        if not emitted and can_fallback(self.inner.call) and self.plan.position<len(self.plan.identifiers):
                            old_frame=self.rewrite(frame)
                            try:
                                self.start()
                            except Exception:
                                # The first attempt is still queryable and known not to have billed.
                                yield old_frame
                                yield 'data: [DONE]\n\n'
                                return
                            retry=True
                            break
                        yield self.rewrite(frame)
                        yield 'data: [DONE]\n\n'
                        return
                    emitted=True
                    yield self.rewrite(frame)
                if retry: continue
                self.inner.call.refresh_from_db()
                self.plan.complete(self.inner.call)
                return
        finally:
            if self.inner is not None:
                self.inner.close()
                self.inner.call.refresh_from_db()
                self.plan.complete(self.inner.call)

    def close(self):
        if self.closed: return
        self.closed=True
        self.iterator.close()
        if self.inner is not None:
            self.inner.close()
            self.inner.call.refresh_from_db()
            self.plan.complete(self.inner.call)
