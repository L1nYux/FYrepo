"""Canonical chat/tool messages across three provider formats."""
import json
import uuid
from urllib.parse import quote
from urllib.parse import urlsplit
from .network import json_request, json_events, TransportError


def native_payload(model, messages, tools, limit, options=None):
    provider=model.provider; options=options or {}; system='\n'.join(m.get('content') or '' for m in messages if m['role']=='system')
    if provider.protocol=='openai':
        clean=[{k:v for k,v in m.items() if not k.startswith('_')} for m in messages]
        body={'model':model.model_id,'messages':clean,'stream':False,model.output_parameter:limit}
        if urlsplit(provider.base_url).hostname == 'api.deepseek.com':
            # Fast workspace queries; thinking tool calls require reasoning_content round trips.
            body['thinking'] = {'type':'disabled'}
        if tools: body.update(tools=tools,tool_choice='auto')
        body.update(options)
        return '/chat/completions',body
    if provider.protocol=='anthropic':
        converted=[]
        for m in messages:
            if m['role']=='system': continue
            if m.get('_native'):
                converted.append({'role':'assistant','content':m['_native']}); continue
            if m['role']=='tool':
                item={'type':'tool_result','tool_use_id':m['tool_call_id'],'content':m['content']}
                if converted and converted[-1]['role']=='user' and isinstance(converted[-1]['content'],list): converted[-1]['content'].append(item)
                else: converted.append({'role':'user','content':[item]})
            elif m.get('tool_calls'):
                blocks=([{'type':'text','text':m['content']}] if m.get('content') else [])
                blocks += [{'type':'tool_use','id':t['id'],'name':t['function']['name'],'input':json.loads(t['function']['arguments'])} for t in m['tool_calls']]
                converted.append({'role':'assistant','content':blocks})
            else: converted.append({'role':m['role'],'content':m.get('content') or ''})
        body={'model':model.model_id,'system':system,'messages':converted,'max_tokens':limit}
        if tools: body['tools']=[{'name':t['function']['name'],'description':t['function']['description'],'input_schema':t['function']['parameters']} for t in tools]
        for key in ('temperature','top_p','stop'): 
            if key in options: body['stop_sequences' if key=='stop' else key]=options[key]
        return '/messages',body
    converted=[]
    tool_names={t['id']:t['function']['name'] for m in messages for t in m.get('tool_calls',[])}
    for m in messages:
        if m['role']=='system': continue
        if m.get('_native'):
            converted.append({'role':'model','parts':m['_native']}); continue
        if m['role']=='tool':
            parts=[{'functionResponse':{'name':tool_names[m['tool_call_id']],'response':{'result':m['content']}}}]; role='user'
        else:
            role='model' if m['role']=='assistant' else 'user'
            parts=([{'text':m['content']}] if m.get('content') else [])
            parts += [{'functionCall':{'name':t['function']['name'],'args':json.loads(t['function']['arguments'])}} for t in m.get('tool_calls',[])]
        if converted and converted[-1]['role']==role: converted[-1]['parts'].extend(parts)
        else: converted.append({'role':role,'parts':parts})
    config={'maxOutputTokens':limit}
    for key,target in [('temperature','temperature'),('top_p','topP'),('stop','stopSequences')]:
        if key in options: config[target]=options[key]
    body={'contents':converted,'generationConfig':config}
    if system: body['systemInstruction']={'parts':[{'text':system}]}
    if tools: body['tools']=[{'functionDeclarations':[{'name':t['function']['name'],'description':t['function']['description'],'parameters':t['function']['parameters']} for t in tools]}]
    return '/models/'+quote(model.model_id,safe='')+':generateContent',body


def invoke(model, secret, messages, tools, limit, options=None, on_progress=None):
    endpoint,body=native_payload(model,messages,tools,limit,options)
    headers={'Content-Type':'application/json'}
    if model.provider.protocol=='anthropic': headers.update({'x-api-key':secret,'anthropic-version':'2023-06-01'})
    elif model.provider.protocol=='gemini': headers['x-goog-api-key']=secret
    else: headers['Authorization']='Bearer '+secret
    url=model.provider.base_url.rstrip('/')+endpoint
    if on_progress is not None and model.provider.protocol=='openai':
        body['stream']=True
        host=urlsplit(model.provider.base_url).hostname or ''
        if not (host=='bigmodel.cn' or host.endswith('.bigmodel.cn')):
            body['stream_options']={'include_usage':True}
        return openai_stream(model,url,headers,body,on_progress)
    raw=json_request(url,headers,body)
    return normalize(model,raw)


def reasoning_text(message):
    value=message.get('reasoning_content') or message.get('reasoning') or ''
    if not value:
        value=''.join(b.get('text','') for b in message.get('reasoning_details',[]) if isinstance(b,dict))
    return value if isinstance(value,str) else ''


def split_thinking(content):
    """Separate leading vendor <think> blocks, including incomplete stream prefixes."""
    reasoning=[]; text=content
    while text.lstrip().startswith('<think>'):
        text=text.lstrip()[7:]
        if '</think>' not in text:
            return '', '\n'.join(reasoning+[text])
        thought,text=text.split('</think>',1); reasoning.append(thought)
    if '<think>'.startswith(text.strip()) and text.strip(): return '', '\n'.join(reasoning)
    return text.lstrip() if reasoning else text, '\n'.join(reasoning)


def openai_stream(model,url,headers,body,on_progress):
    message={'role':'assistant','content':'','tool_calls':[]}; reasoning=''; usage=None; request_id=''; finished=False
    calls={}
    for chunk in json_events(url,headers,body):
        if chunk.get('error'): raise TransportError('upstream_stream_error',True)
        request_id=str(chunk.get('id') or request_id)
        if chunk.get('usage') is not None: usage=chunk['usage']
        choices=chunk.get('choices') or []
        if not choices: continue
        choice=choices[0]
        if 'message' in choice:
            result=normalize(model,chunk)
            on_progress({'text':result['text'],'reasoning':result.get('reasoning','')})
            return result
        delta=choice.get('delta') or {}
        part=delta.get('content') or ''
        if not isinstance(part,str): raise TransportError('invalid_response',True)
        message['content']+=part; reasoning+=reasoning_text(delta)
        for call in delta.get('tool_calls') or []:
            index=call.get('index',0)
            if not isinstance(index,int) or index<0 or index>31: raise TransportError('invalid_response',True)
            value=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
            if call.get('id'): value['id']=call['id']
            function=call.get('function') or {}
            for key in ('name','arguments'):
                if function.get(key): value['function'][key]+=function[key]
        text,inline=split_thinking(message['content'])
        on_progress({'text':text,'reasoning':reasoning or inline})
        if choice.get('finish_reason') is not None: finished=True
    if not finished: raise TransportError('incomplete_stream',True)
    message['tool_calls']=[calls[k] for k in sorted(calls)]
    if reasoning: message['reasoning_content']=reasoning
    return normalize(model,{'id':request_id,'choices':[{'message':message}],'usage':usage})


def normalize(model, raw):
    protocol=model.provider.protocol; native=None; calls=[]; reasoning=''; assistant_message=None
    if protocol=='openai':
        message=(raw.get('choices') or [{}])[0].get('message') or {}
        usage=raw.get('usage'); text=message.get('content') or ''; calls=message.get('tool_calls') or []
        assistant_message={k:message[k] for k in ('role','content','tool_calls','reasoning_content','reasoning','reasoning_details') if k in message}
        reasoning=reasoning_text(message)
        if isinstance(text,str):
            text,inline=split_thinking(text); reasoning=reasoning or inline
        counts=None
        if usage and isinstance(usage.get('prompt_tokens'),int) and isinstance(usage.get('completion_tokens'),int):
            details=usage.get('prompt_tokens_details') or {}; out=usage.get('completion_tokens_details') or {}
            counts={'input_tokens':usage['prompt_tokens'],'output_tokens':usage['completion_tokens'],
                'cached_tokens':details.get('cached_tokens',usage.get('prompt_cache_hit_tokens',0)),
                'cache_write_tokens':details.get('cache_write_tokens',0),'reasoning_tokens':out.get('reasoning_tokens',0)}
    elif protocol=='anthropic':
        native=raw.get('content') or []; text='\n'.join(b.get('text','') for b in native if b.get('type')=='text'); usage=raw.get('usage'); counts=None
        reasoning='\n'.join(b.get('thinking','') for b in native if b.get('type')=='thinking')
        calls=[{'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':json.dumps(b['input'],ensure_ascii=False)}} for b in native if b.get('type')=='tool_use']
        if usage and isinstance(usage.get('input_tokens'),int) and isinstance(usage.get('output_tokens'),int):
            cached=usage.get('cache_read_input_tokens') or 0; write=usage.get('cache_creation_input_tokens') or 0
            counts={'input_tokens':usage['input_tokens']+cached+write,'output_tokens':usage['output_tokens'],
                'cached_tokens':cached,'cache_write_tokens':write,'reasoning_tokens':(usage.get('output_tokens_details') or {}).get('thinking_tokens',0)}
    else:
        native=(raw.get('candidates') or [{}])[0].get('content',{}).get('parts',[])
        text='\n'.join(b.get('text','') for b in native if 'text' in b and not b.get('thought'))
        reasoning='\n'.join(b.get('text','') for b in native if b.get('thought') and isinstance(b.get('text'),str))
        calls=[{'id':'tool_'+uuid.uuid4().hex,'type':'function','function':{'name':b['functionCall']['name'],'arguments':json.dumps(b['functionCall'].get('args',{}),ensure_ascii=False)}} for b in native if 'functionCall' in b]
        usage=raw.get('usageMetadata'); counts=None
        if usage and isinstance(usage.get('promptTokenCount'),int) and isinstance(usage.get('totalTokenCount'),int):
            counts={'input_tokens':usage['promptTokenCount'],'output_tokens':max(0,usage['totalTokenCount']-usage['promptTokenCount']),
                'cached_tokens':usage.get('cachedContentTokenCount',0),'cache_write_tokens':0,'reasoning_tokens':usage.get('thoughtsTokenCount',0)}
    if not isinstance(text,str) or not isinstance(calls,list): raise TransportError('invalid_response',True)
    if counts and (any(not isinstance(v,int) or v<0 for v in counts.values()) or counts['cached_tokens']+counts['cache_write_tokens']>counts['input_tokens']): counts=None
    result={'text':text,'tool_calls':calls,'counts':counts,'id':str(raw.get('id') or raw.get('responseId') or '')[:200]}
    if reasoning: result['reasoning']=reasoning[:160000]
    if assistant_message is not None: result['assistant_message']=assistant_message
    if native is not None: result['native']=native
    return result
