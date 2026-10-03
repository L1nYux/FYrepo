"""Canonical chat/tool messages across three provider formats."""
import json
import uuid
from urllib.parse import quote
from urllib.parse import urlsplit
from .network import json_request, TransportError


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


def invoke(model, secret, messages, tools, limit, options=None):
    endpoint,body=native_payload(model,messages,tools,limit,options)
    headers={'Content-Type':'application/json'}
    if model.provider.protocol=='anthropic': headers.update({'x-api-key':secret,'anthropic-version':'2023-06-01'})
    elif model.provider.protocol=='gemini': headers['x-goog-api-key']=secret
    else: headers['Authorization']='Bearer '+secret
    raw=json_request(model.provider.base_url.rstrip('/')+endpoint,headers,body)
    return normalize(model,raw)


def normalize(model, raw):
    protocol=model.provider.protocol; native=None; calls=[]
    if protocol=='openai':
        message=(raw.get('choices') or [{}])[0].get('message') or {}
        usage=raw.get('usage'); text=message.get('content') or ''; calls=message.get('tool_calls') or []
        counts=None
        if usage and isinstance(usage.get('prompt_tokens'),int) and isinstance(usage.get('completion_tokens'),int):
            details=usage.get('prompt_tokens_details') or {}; out=usage.get('completion_tokens_details') or {}
            counts={'input_tokens':usage['prompt_tokens'],'output_tokens':usage['completion_tokens'],
                'cached_tokens':details.get('cached_tokens',usage.get('prompt_cache_hit_tokens',0)),
                'cache_write_tokens':details.get('cache_write_tokens',0),'reasoning_tokens':out.get('reasoning_tokens',0)}
    elif protocol=='anthropic':
        native=raw.get('content') or []; text='\n'.join(b.get('text','') for b in native if b.get('type')=='text'); usage=raw.get('usage'); counts=None
        calls=[{'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':json.dumps(b['input'],ensure_ascii=False)}} for b in native if b.get('type')=='tool_use']
        if usage and isinstance(usage.get('input_tokens'),int) and isinstance(usage.get('output_tokens'),int):
            cached=usage.get('cache_read_input_tokens') or 0; write=usage.get('cache_creation_input_tokens') or 0
            counts={'input_tokens':usage['input_tokens']+cached+write,'output_tokens':usage['output_tokens'],
                'cached_tokens':cached,'cache_write_tokens':write,'reasoning_tokens':(usage.get('output_tokens_details') or {}).get('thinking_tokens',0)}
    else:
        native=(raw.get('candidates') or [{}])[0].get('content',{}).get('parts',[])
        text='\n'.join(b.get('text','') for b in native if 'text' in b and not b.get('thought'))
        calls=[{'id':'tool_'+uuid.uuid4().hex,'type':'function','function':{'name':b['functionCall']['name'],'arguments':json.dumps(b['functionCall'].get('args',{}),ensure_ascii=False)}} for b in native if 'functionCall' in b]
        usage=raw.get('usageMetadata'); counts=None
        if usage and isinstance(usage.get('promptTokenCount'),int) and isinstance(usage.get('totalTokenCount'),int):
            counts={'input_tokens':usage['promptTokenCount'],'output_tokens':max(0,usage['totalTokenCount']-usage['promptTokenCount']),
                'cached_tokens':usage.get('cachedContentTokenCount',0),'cache_write_tokens':0,'reasoning_tokens':usage.get('thoughtsTokenCount',0)}
    if not isinstance(text,str) or not isinstance(calls,list): raise TransportError('invalid_response',True)
    if counts and (any(not isinstance(v,int) or v<0 for v in counts.values()) or counts['cached_tokens']+counts['cache_write_tokens']>counts['input_tokens']): counts=None
    result={'text':text,'tool_calls':calls,'counts':counts,'id':str(raw.get('id') or raw.get('responseId') or '')[:200]}
    if native is not None: result['native']=native
    return result
