"""Authenticated model discovery; no inference requests or keys in the returned catalog."""
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit
from django.core.exceptions import ValidationError
from .network import json_request, TransportError, validate_url
from .model_catalog import describe
from .tool_policy import supports_tools

PRESETS = {
    'minimax': {'name':'MiniMax','protocol':'openai','base_url':'https://api.minimaxi.com/v1'},
    'qwen': {'name':'千问 · 百炼','protocol':'openai','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1'},
    'zhipu': {'name':'智谱','protocol':'openai','base_url':'https://open.bigmodel.cn/api/paas/v4'},
    'deepseek': {'name':'DeepSeek','protocol':'openai','base_url':'https://api.deepseek.com'},
    'openai': {'name':'OpenAI','protocol':'openai','base_url':'https://api.openai.com/v1'},
    'anthropic': {'name':'Anthropic','protocol':'anthropic','base_url':'https://api.anthropic.com/v1'},
    'gemini': {'name':'Google Gemini','protocol':'gemini','base_url':'https://generativelanguage.googleapis.com/v1beta'},
    'openrouter': {'name':'OpenRouter','protocol':'openai','base_url':'https://openrouter.ai/api/v1'},
}
LIMIT=300


def preset_for(provider):
    for code, value in PRESETS.items():
        if provider.protocol==value['protocol'] and provider.base_url.rstrip('/')==value['base_url']:
            return code
    return 'custom'


def connection(data):
    base_url=validate_url(str(data.get('base_url','')).strip())
    for preset in PRESETS.values():
        if base_url in (preset['base_url'],preset['base_url']+'/v1' if preset['name']=='DeepSeek' else preset['base_url']):
            return dict(preset)
    if base_url=='https://api.deepseek.com/anthropic':
        return {'name':'DeepSeek','protocol':'anthropic','base_url':base_url}
    name=str(data.get('name','')).strip() or urlsplit(base_url).hostname[:80]
    protocol=data.get('protocol') or 'openai'
    if not 1<=len(name)<=80 or protocol not in ('openai','anthropic','gemini'):
        raise ValidationError('请填写连接名称并选择接口格式。')
    return {'name':name,'protocol':protocol,'base_url':base_url}


def model_label(identifier, fallback=''):
    if identifier in ('deepseek-flash','deepseek-v4-flash','deepseek-v4-flash-vision-exp'): return 'DeepSeek-V4.1-Flash'
    if identifier=='deepseek-v4-pro': return 'DeepSeek-V4-Pro'
    return fallback or identifier


def clean_key(value):
    if not isinstance(value,str): raise ValidationError('API Key 格式无效。')
    value=value.strip()
    if len(value)>2000 or any(ord(c)<33 or ord(c)>126 for c in value):
        raise ValidationError('API Key 不应包含空格或换行。')
    return value


def listed_price(provider, row):
    host=urlsplit(provider.base_url).hostname
    pricing=row.get('pricing')
    if not isinstance(pricing,dict): return None
    try:
        # OpenRouter's model catalog quotes USD per token, not per million tokens.
        if host=='openrouter.ai':
            rate=lambda name: str(Decimal(str(pricing[name]))*1000000)
            if any(Decimal(str(pricing.get(k,0)))!=0 for k in ('request','image','web_search','internal_reasoning')):
                return None  # These extra billable units are not represented in the text meter.
            values={'currency':'USD','input_rate':rate('prompt'),'output_rate':rate('completion'),
                'cached_rate':rate('input_cache_read') if pricing.get('input_cache_read') is not None else rate('prompt'),
                'cache_write_rate':rate('input_cache_write') if pricing.get('input_cache_write') is not None else rate('prompt'),
                'source':'自动读取：'+provider.base_url.rstrip('/')+'/models'}
            if all(Decimal(values[k]).is_finite() and 0<=Decimal(values[k])<=100000 for k in ('input_rate','output_rate','cached_rate','cache_write_rate')):
                return values
    except (KeyError,InvalidOperation,ValueError): pass
    return None


def fetch_models(provider, key):
    if not key: raise ValidationError('首次连接需要填写 API Key。')
    base=provider.base_url.rstrip('/'); rows=[]; cursor=None; seen_cursors=set(); truncated=False
    headers={'Authorization':'Bearer '+key}
    if provider.protocol=='anthropic': headers={'x-api-key':key,'anthropic-version':'2023-06-01'}
    elif provider.protocol=='gemini': headers={'x-goog-api-key':key}
    try:
        for page in range(4):
            params={}
            if provider.protocol=='anthropic':
                params={'limit':100}
                if cursor: params['after_id']=cursor
            elif provider.protocol=='gemini':
                params={'pageSize':100}
                if cursor: params['pageToken']=cursor
            url=base+'/models'+('?' + urlencode(params) if params else '')
            data=json_request(url,headers,timeout=20,allow_query=True)
            batch=data.get('models') if provider.protocol=='gemini' else data.get('data')
            if not isinstance(batch,list): raise ValidationError('接口没有返回模型列表，请检查接口格式和基础地址。')
            rows.extend(batch)
            cursor=(data.get('nextPageToken') if provider.protocol=='gemini' else data.get('last_id') if data.get('has_more') else None)
            if len(rows)>=LIMIT or not cursor: truncated=bool(cursor) or len(rows)>LIMIT; break
            if cursor in seen_cursors: truncated=True; break
            seen_cursors.add(cursor)
        else: truncated=bool(cursor)
    except TransportError as exc:
        explanation={'http_401':'API Key 无效或已过期。','http_403':'此 Key 没有读取模型的权限。',
            'http_404':'该连接没有模型列表接口，可展开高级设置手动添加模型。',
            'private_endpoint':'接口解析到被阻止的内网地址，请检查代理或接口地址。',
            'connection_interrupted':'连接超时或中断，请检查网络、代理及接口地址。',
            'dns_error':'域名解析失败，请检查网络或接口地址。'}
        raise ValidationError(explanation.get(exc.code,'读取模型失败（'+exc.code+'），请检查连接。')) from None
    result=[]; seen=set(); host=urlsplit(base).hostname
    for row in rows[:LIMIT]:
        if not isinstance(row,dict): continue
        identifier=row.get('id')
        if not identifier and isinstance(row.get('name'),str): identifier=row['name'].removeprefix('models/')
        if not isinstance(identifier,str) or not 1<=len(identifier)<=160 or identifier in seen: continue
        description=describe(identifier,row)
        if provider.protocol=='gemini' and 'generateContent' not in row.get('supportedGenerationMethods',[]):
            description.update(assistant_supported=False,unavailable_reason='当前助手暂不支持此接口')
        if host=='api.openai.com' and (not identifier.startswith(('gpt-','chatgpt-','o1','o3','o4','ft:')) or any(word in identifier for word in ('-codex','-pro'))):
            description.update(assistant_supported=False,unavailable_reason='当前助手暂不支持此接口')
        seen.add(identifier)
        tools=supports_tools(provider,identifier,row)
        limit=row.get('max_output_tokens') or row.get('max_tokens') or row.get('outputTokenLimit') or 2048
        limit=max(64,min(int(limit),2048)) if isinstance(limit,(int,float)) else 2048
        parameter='max_completion_tokens' if host=='api.openai.com' and identifier.startswith(('gpt-5','gpt-6','o1','o3','o4')) else 'max_tokens'
        from .images import catalog_capability
        result.append({**description,'id':identifier,'supports_images':catalog_capability(row),'label':model_label(identifier,str(row.get('display_name') or row.get('displayName') or row.get('name') or identifier)[:100]),
            'supports_tools':tools,'max_output_tokens':limit,'output_parameter':parameter,'price':listed_price(provider,{**row,'id':identifier})})
    if not result: raise ValidationError('连接成功，但没有返回模型。可在高级设置手动添加。')
    return result, truncated
