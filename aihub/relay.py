"""Public relay contract. Keys authorize billing; they never expose provider secrets."""
import json
import math
import re
from decimal import Decimal
from django.core.exceptions import ValidationError, RequestDataTooBig
from django.db.models import Sum, Q
from django.utils import timezone
from .models import Call, MemberToken, PoolModel


class RelayError(ValidationError):
    def __init__(self, message, code='invalid_request', status=400, *, call_id=None):
        super().__init__(message)
        self.api_code, self.http_status, self.call_id = code, status, call_id


def token_usage(token):
    records = Call.objects.filter(api_token=token)
    value = records.aggregate(spent=Sum('cost_cny', filter=Q(status='success')),
                              reserved=Sum('reserved_cny', filter=Q(status__in=['running', 'unknown'])))
    spent, reserved = value['spent'] or Decimal('0'), value['reserved'] or Decimal('0')
    return {'spent_cny': str(spent), 'reserved_cny': str(reserved),
            'limit_cny': str(token.cost_limit_cny) if token.cost_limit_cny is not None else None,
            'remaining_cny': str(max(Decimal('0'), token.cost_limit_cny-spent-reserved)) if token.cost_limit_cny is not None else None}


def check_token(token, model=None, amount=None):
    if token.revoked_at or token.expires_at and token.expires_at <= timezone.now():
        raise RelayError('API Key 已过期或撤销，请重新生成。', 'invalid_api_key', 401)
    if model is not None and token.allowed_models and model.pk not in token.allowed_models:
        raise RelayError('此 API Key 未授权使用这个模型。', 'model_not_allowed', 403)
    if amount is not None and token.cost_limit_cny is not None:
        value = token_usage(token)
        if Decimal(value['spent_cny']) + Decimal(value['reserved_cny']) + amount > token.cost_limit_cny:
            raise RelayError('此 API Key 的剩余额度不足，请换用有额度的 Key 或重新生成。', 'key_quota_exceeded', 429)


def key_options(form):
    days = str(form.get('expires_days', '')).strip()
    if days not in ('', '7', '30', '90', '365'):
        raise ValidationError('请选择有效的 Key 有效期。')
    raw = str(form.get('cost_limit_cny', '')).strip()
    if raw and not re.fullmatch(r'\d{1,8}(?:\.\d{1,2})?', raw):
        raise ValidationError('Key 额度应为非负金额，最多两位小数。')
    identifiers = form.getlist('allowed_models')
    if len(identifiers) > 200 or any(not v.isascii() or not v.isdecimal() or len(v) > 18 for v in identifiers):
        raise ValidationError('模型范围无效。')
    identifiers = sorted(set(map(int, identifiers)))
    if set(identifiers) - set(PoolModel.objects.filter(pk__in=identifiers, enabled=True, provider__enabled=True).values_list('pk', flat=True)):
        raise ValidationError('所选模型已停用或不属于当前团队。')
    return {'expires_at': timezone.now()+timezone.timedelta(days=int(days)) if days else None,
            'cost_limit_cny': Decimal(raw) if raw else None, 'allowed_models': identifiers}


def read_body(request):
    try:body=request.body
    except RequestDataTooBig:raise RelayError('请求过长。','request_too_large',413) from None
    if len(body) > 220000:
        raise RelayError('请求过长。', 'request_too_large', 413)
    def invalid_constant(value):
        raise ValueError('Non-finite JSON number')
    try:
        value = json.loads(body, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise RelayError('请求必须是有效的 JSON 对象。') from None
    if not isinstance(value, dict):
        raise RelayError('请求必须是 JSON 对象。')
    return value


def chat_payload(data, model):
    supported = {'model','messages','stream','stream_options','tools','tool_choice','parallel_tool_calls',
                 'temperature','top_p','stop','max_tokens','max_completion_tokens','project_id','experiment_id',
                 'n','response_format','reasoning_effort','thinking','frequency_penalty','presence_penalty','seed','user'}
    if set(data)-supported:
        raise RelayError('不支持的参数：'+', '.join(sorted(set(data)-supported)), 'unsupported_parameter')
    if 'max_tokens' in data and 'max_completion_tokens' in data:
        raise RelayError('输出上限参数只填一种。')
    if type(data.get('n',1)) is not int or data.get('n',1) != 1:
        raise RelayError('当前只支持 n=1。')
    if type(data.get('stream',False)) is not bool:
        raise RelayError('stream 必须是布尔值。')
    stream_options = data.get('stream_options')
    if stream_options is None: stream_options = {}
    if not isinstance(stream_options,dict) or set(stream_options)-{'include_usage'} or type(stream_options.get('include_usage',False)) is not bool:
        raise RelayError('stream_options 格式无效。')
    history = data.get('messages')
    if not isinstance(history,list) or not 1 <= len(history) <= 80:
        raise RelayError('messages 应为 1–80 条消息。')
    messages, pending = [], set()
    for source in history:
        if not isinstance(source,dict) or source.get('role') not in ('system','developer','user','assistant','tool'):
            raise RelayError('消息角色无效。')
        if set(source)-{'role','content','name','tool_calls','tool_call_id','reasoning_content'}:
            raise RelayError('消息包含不支持的字段。')
        row = dict(source)
        if row['role']=='developer' and model.provider.protocol!='openai': row['role']='system'
        content = row.get('content')
        if isinstance(content,list):
            if any(not isinstance(part,dict) or set(part)-{'type','text'} or part.get('type')!='text' or not isinstance(part.get('text'),str) for part in content):
                raise RelayError('外部 API 当前支持文本及文本分段，图片请使用内置助手上传。', 'unsupported_content')
            content = '\n'.join(part['text'] for part in content)
        if content is not None and not isinstance(content,str) or len(content or '') > 100000:
            raise RelayError('消息内容无效或过长。')
        row['content'] = content
        if 'name' in row and (not isinstance(row['name'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',row['name'])):
            raise RelayError('消息 name 无效。')
        if 'reasoning_content' in row and (row['role']!='assistant' or not isinstance(row['reasoning_content'],str)):
            raise RelayError('reasoning_content 无效。')
        if row['role']=='tool':
            identifier = row.get('tool_call_id')
            if not isinstance(identifier,str) or identifier not in pending or content is None:
                raise RelayError('工具结果应对应前一条助手消息的 tool_call_id。')
            pending.remove(identifier)
        else:
            if pending: raise RelayError('请先补齐所有工具调用的结果。')
            if 'tool_call_id' in row: raise RelayError('tool_call_id 只能出现在工具结果中。')
        calls = row.get('tool_calls')
        if calls is not None:
            if row['role']!='assistant' or not isinstance(calls,list) or not 1 <= len(calls) <= 32:
                raise RelayError('tool_calls 格式无效。')
            for call in calls:
                function = call.get('function') if isinstance(call,dict) else None
                identifier = call.get('id') if isinstance(call,dict) else None
                if not isinstance(identifier,str) or not 1 <= len(identifier) <= 200 or identifier in pending or call.get('type')!='function' or set(call)-{'id','type','function'} or not isinstance(function,dict) or set(function)-{'name','arguments'} or not isinstance(function.get('name'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',function['name']) or not isinstance(function.get('arguments'),str):
                    raise RelayError('工具调用格式无效。')
                def invalid_constant(value): raise ValueError('Non-finite JSON number')
                try: arguments=json.loads(function['arguments'],parse_constant=invalid_constant)
                except (ValueError,RecursionError): raise RelayError('工具参数必须是 JSON 对象。') from None
                if not isinstance(arguments,dict): raise RelayError('工具参数必须是 JSON 对象。')
                pending.add(identifier)
        if content is None and (row['role']!='assistant' or not calls): raise RelayError('消息内容不能为空。')
        messages.append(row)
    if pending: raise RelayError('请补齐工具结果后再调用模型。')
    tools = data.get('tools')
    if tools is None: tools=[]
    if not isinstance(tools,list) or len(tools)>12: raise RelayError('工具定义无效。')
    names=set(); clean_tools=[]
    for tool in tools:
        function=tool.get('function') if isinstance(tool,dict) else None
        if not isinstance(function,dict) or tool.get('type')!='function' or not isinstance(function.get('name'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',function['name']) or function['name'] in names or not isinstance(function.get('parameters'),dict) or not isinstance(function.get('description',''),str):
            raise RelayError('工具定义无效。')
        if set(tool)-{'type','function'} or set(function)-{'name','description','parameters','strict'} or 'strict' in function and type(function['strict']) is not bool:
            raise RelayError('工具定义包含不支持的字段。')
        if 'strict' in function and model.provider.protocol!='openai': raise RelayError('strict 工具当前需要 OpenAI 兼容上游。')
        names.add(function['name']); clean_tools.append({'type':'function','function':{**function,'description':function.get('description','')}})
    if clean_tools and not model.supports_tools: raise RelayError('该模型未启用工具调用。')
    options={}
    for name, low, high in [('temperature',0,2),('top_p',0,1),('frequency_penalty',-2,2),('presence_penalty',-2,2)]:
        if name not in data: continue
        value=data[name]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not low <= value <= high or isinstance(value,float) and not math.isfinite(value):
            raise RelayError(name+' 无效。')
        options[name]=value
    if 'stop' in data and data['stop'] is not None:
        stop=[data['stop']] if isinstance(data['stop'],str) else data['stop']
        if not isinstance(stop,list) or not 1 <= len(stop) <= 4 or any(not isinstance(s,str) or not 1 <= len(s) <= 200 for s in stop): raise RelayError('stop 参数无效。')
        options['stop']=stop
    if 'tool_choice' in data and data['tool_choice'] is not None:
        choice=data['tool_choice']
        if isinstance(choice,str):
            if choice not in ('auto','none','required') or choice!='none' and not tools: raise RelayError('tool_choice 无效。')
        elif isinstance(choice,dict):
            if set(choice)!={'type','function'} or choice['type']!='function' or not isinstance(choice['function'],dict) or set(choice['function'])!={'name'} or choice['function']['name'] not in names:
                raise RelayError('tool_choice 指定的工具不存在。')
        else: raise RelayError('tool_choice 无效。')
        options['tool_choice']=choice
    for name in ('parallel_tool_calls','seed','user','response_format','reasoning_effort','thinking'):
        if name in data and data[name] is not None: options[name]=data[name]
    if 'parallel_tool_calls' in options and type(options['parallel_tool_calls']) is not bool: raise RelayError('parallel_tool_calls 必须是布尔值。')
    if 'seed' in options and (type(options['seed']) is not int or not -(2**63) <= options['seed'] < 2**63): raise RelayError('seed 无效。')
    if 'user' in options and (not isinstance(options['user'],str) or len(options['user'])>200): raise RelayError('user 无效。')
    if 'reasoning_effort' in options and options['reasoning_effort'] not in ('none','minimal','low','medium','high','xhigh'): raise RelayError('reasoning_effort 无效。')
    if 'thinking' in options and (not isinstance(options['thinking'],dict) or set(options['thinking'])!={'type'} or options['thinking']['type'] not in ('enabled','disabled')): raise RelayError('thinking 无效。')
    if 'response_format' in options:
        fmt=options['response_format']
        if not isinstance(fmt,dict) or fmt.get('type') not in ('text','json_object','json_schema') or set(fmt)-{'type','json_schema'}: raise RelayError('response_format 无效。')
        if fmt['type']=='json_schema':
            schema=fmt.get('json_schema')
            if not isinstance(schema,dict) or not isinstance(schema.get('name'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',schema['name']) or not isinstance(schema.get('schema'),dict) or set(schema)-{'name','schema','strict','description'} or 'strict' in schema and type(schema['strict']) is not bool:
                raise RelayError('json_schema 格式无效。')
        elif 'json_schema' in fmt: raise RelayError('json_schema 只能用于 json_schema 输出。')
    if model.provider.protocol!='openai' and set(options)-{'temperature','top_p','stop'}:
        raise RelayError('所选原生协议暂不支持这些参数：'+', '.join(sorted(set(options)-{'temperature','top_p','stop'})), 'unsupported_parameter')
    limit=data.get('max_completion_tokens',data.get('max_tokens'))
    if limit is None: limit=model.max_output_tokens
    if type(limit) is not int or not 1 <= limit <= model.max_output_tokens:
        raise RelayError('输出 token 上限应为 1–'+str(model.max_output_tokens)+'。')
    return {'messages':messages,'tools':clean_tools,'limit':limit,'options':options,
            'stream':data.get('stream',False),'include_usage':stream_options.get('include_usage',False)}
