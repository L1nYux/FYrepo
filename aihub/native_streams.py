"""Incremental native streams shared by the chat relay and built-in assistant."""
import json
from .network import json_events,TransportError
from .timeouts import CONNECT_SECONDS,READ_SECONDS,STREAM_TOTAL_SECONDS

def stream(model,secret,messages,tools,limit,options=None):
    from .providers import native_payload,normalize
    endpoint,body=native_payload(model,messages,tools,limit,options)
    protocol=model.provider.protocol
    headers={'Content-Type':'application/json'}
    if protocol=='anthropic':
        headers.update({'x-api-key':secret,'anthropic-version':'2023-06-01'});body['stream']=True
    elif protocol=='gemini':
        headers['x-goog-api-key']=secret
        endpoint=endpoint.replace(':generateContent',':streamGenerateContent')+'?alt=sse'
    else:raise ValueError('A native protocol is required.')
    source=json_events(model.provider.base_url.rstrip('/')+endpoint,headers,body,
        timeout=READ_SECONDS,connect_timeout=CONNECT_SECONDS,total_timeout=STREAM_TOTAL_SECONDS,allow_query=protocol=='gemini')
    blocks={};arguments={};identifier='';usage={};finish=None;stopped=False;parts=[];tool_count=0
    try:
        for event in source:
            if event.get('error') or event.get('type')=='error':raise TransportError('upstream_stream_error',True)
            if protocol=='anthropic':
                kind=event.get('type')
                if kind=='message' and 'content' in event:
                    result=normalize(model,event)
                    yield {'delta':{'content':result['text'],**({'reasoning_content':result['reasoning']} if result.get('reasoning') else {})}}
                    if result['tool_calls']:
                        yield {'delta':{'tool_calls':[{'index':index,**call} for index,call in enumerate(result['tool_calls'])]}}
                    yield {'result':result};return
                if kind=='message_start':
                    message=event.get('message') or {};identifier=message.get('id','');usage.update(message.get('usage') or {})
                elif kind=='content_block_start':
                    index=event.get('index');block=dict(event.get('content_block') or {})
                    if type(index) is not int or not 0<=index<1024:raise TransportError('invalid_response',True)
                    blocks[index]=block
                    if block.get('type')=='tool_use':
                        block['_tool_index']=tool_count;tool_count+=1
                        yield {'delta':{'tool_calls':[{'index':block['_tool_index'],'id':block['id'],'type':'function',
                            'function':{'name':block['name'],'arguments':''}}]}}
                    elif block.get('text'):yield {'delta':{'content':block['text']}}
                    elif block.get('thinking'):yield {'delta':{'reasoning_content':block['thinking']}}
                elif kind=='content_block_delta':
                    index=event.get('index');delta=event.get('delta') or {};block=blocks.get(index)
                    if block is None:raise TransportError('invalid_response',True)
                    delta_kind=delta.get('type')
                    if delta_kind in ('text_delta','thinking_delta','signature_delta'):
                        key={'text_delta':'text','thinking_delta':'thinking','signature_delta':'signature'}[delta_kind]
                        value=delta.get(key,'')
                        if not isinstance(value,str):raise TransportError('invalid_response',True)
                        block[key]=block.get(key,'')+value
                        if delta_kind!='signature_delta':yield {'delta':{'content' if key=='text' else 'reasoning_content':value}}
                    elif delta_kind=='input_json_delta':
                        value=delta.get('partial_json','')
                        if not isinstance(value,str):raise TransportError('invalid_response',True)
                        arguments[index]=arguments.get(index,'')+value
                        yield {'delta':{'tool_calls':[{'index':block['_tool_index'],'function':{'arguments':value}}]}}
                elif kind=='message_delta':
                    usage.update(event.get('usage') or {});finish=(event.get('delta') or {}).get('stop_reason',finish)
                elif kind=='message_stop':stopped=True
            else:
                identifier=event.get('responseId') or identifier
                usage.update(event.get('usageMetadata') or {})
                for candidate in event.get('candidates') or []:
                    if candidate.get('index',0)!=0:continue
                    finish=candidate.get('finishReason') or finish
                    for part in (candidate.get('content') or {}).get('parts',[]):
                        if 'text' in part:
                            text=part['text']
                            if not isinstance(text,str):raise TransportError('invalid_response',True)
                            if parts and 'text' in parts[-1] and bool(parts[-1].get('thought'))==bool(part.get('thought')):
                                parts[-1]['text']+=text
                                if part.get('thoughtSignature'):parts[-1]['thoughtSignature']=part['thoughtSignature']
                            else:parts.append(dict(part))
                            yield {'delta':{'reasoning_content' if part.get('thought') else 'content':text}}
                        elif 'functionCall' in part:
                            parts.append(dict(part));call=part['functionCall']
                            yield {'delta':{'tool_calls':[{'index':tool_count,'id':'tool_'+str(tool_count),'type':'function',
                                'function':{'name':call['name'],'arguments':json.dumps(call.get('args',{}),ensure_ascii=False)}}]}}
                            tool_count+=1
                        else:parts.append(dict(part))
        if protocol=='anthropic':
            if not stopped or finish is None:raise TransportError('incomplete_stream',True)
            for index,argument in arguments.items():blocks[index]['input']=json.loads(argument)
            clean=[{key:value for key,value in blocks[index].items() if not key.startswith('_')} for index in sorted(blocks)]
            raw={'id':identifier,'content':clean,'usage':usage,'stop_reason':finish}
        else:
            if finish is None:raise TransportError('incomplete_stream',True)
            raw={'responseId':identifier,'candidates':[{'content':{'parts':parts},'finishReason':finish}],'usageMetadata':usage}
        result=normalize(model,raw)
        if protocol=='gemini' and tool_count:
            for index,call in enumerate(result['tool_calls']):call['id']='tool_'+str(index)
        yield {'result':result}
    except (ValueError,KeyError,TypeError):raise TransportError('invalid_stream',True) from None
    finally:
        close=getattr(source,'close',None)
        if close:close()
