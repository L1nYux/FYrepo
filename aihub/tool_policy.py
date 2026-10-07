"""Shared read-only tool requirements; model prose is never executable input."""
import re
from urllib.parse import urlsplit
from .model_catalog import describe


def supports_tools(provider, identifier, row=None):
    row = row or {}
    if type(row.get('supports_tools')) is bool:
        return row['supports_tools']
    parameters = row.get('supported_parameters')
    if isinstance(parameters, (list, dict)):
        return 'tools' in parameters
    if not describe(identifier, row)['assistant_supported']:
        return False
    host = (urlsplit(provider.base_url).hostname or '').lower()
    name = identifier.lower().removeprefix('models/')
    if host in ('api.anthropic.com', 'generativelanguage.googleapis.com'):
        return True
    if host == 'api.openai.com':
        return name.startswith(('gpt-', 'chatgpt-', 'o1', 'o3', 'o4', 'ft:'))
    if host == 'api.deepseek.com':
        return name.startswith('deepseek-')
    if host in ('api.minimax.io', 'api.minimaxi.com', 'api.minimax.cn'):
        return name.startswith('minimax-m') and not name.startswith('minimax-m2-her')
    if host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'coding.dashscope.aliyuncs.com'):
        return name.startswith(('qwen-max', 'qwen-plus', 'qwen-turbo', 'qwen2.5-', 'qwen3'))
    if host == 'bigmodel.cn' or host.endswith('.bigmodel.cn'):
        return name.startswith(('glm-4', 'glm-5'))
    # Unknown proxies/models remain opt-in. Explicit catalog metadata wins.
    return False


def search_query(text):
    """Remove request wrappers, not subject words; never extract commands from replies."""
    value=str(text or '').strip()[:300]
    prefix=r'^(?:(?:请问|请|麻烦|你好[，,]?)\s*)?(?:你\s*)?(?:(?:能不能|可不可以|能否|可以|能)\s*)?(?:(?:帮我|帮忙|替我|给我|为我)\s*)?(?:(?:在网上|在互联网|网上|互联网|联网|上网)\s*)?(?:搜索(?!引擎|算法|技术|功能|结果|服务)|搜一下|搜一搜|查找|查一下|查一查|查询|查下|找一下|找找)\s*'
    value=re.sub(prefix,'',value)
    value=re.sub(r'^(?:一下|一下子)\s*','',value)
    value=re.sub(r'^(?:有关|关于|什么是|什么叫)\s*','',value)
    value=re.sub(r'^(?:please\s+)?(?:can|could|would)\s+you\s+(?:help\s+me\s+)?(?:search(?:\s+for)?|look\s+up|find|check)\s+','',value,flags=re.I)
    value=re.sub(r'^(?:please\s+)?(?:search(?:\s+for)?|look\s+up|find|what\s+is)\s+','',value,flags=re.I)
    value=re.sub(r'(?:的信息|的资料)?(?:[吗呢])?[。？?！!，,；;]*\s*$','',value).strip()
    value=re.sub(r'(?<![a-z0-9_])(?:brenchmark|brechmark|benchamrk|benckmark)(?![a-z0-9_])','benchmark',value,flags=re.I)
    return value or str(text or '').strip()[:300]


def focused_query(query, requirements):
    """Keep user topic anchors in model refinements; search-engine names are not topics."""
    query=search_query(query)
    anchors=[item.get('args',{}).get('query','') for item in requirements if item.get('tool')=='search_web']
    if not anchors:
        return query
    original=search_query(anchors[0])
    filler={'the','and','for','with','please','what','how','search','find','about','latest','information'}
    terms=set(re.findall(r'[a-z][a-z0-9_-]{2,}',original.lower()))-filler
    refined=set(re.findall(r'[a-z][a-z0-9_-]{2,}',query.lower()))
    if not terms.issubset(refined):
        return original
    if re.fullmatch(r'(?:百度|必应|谷歌|搜狗|baidu|bing|google)(?:搜索|一下|官网|首页|主页)?',query,re.I) and query.casefold()!=original.casefold():
        return original
    return query


def requirements(text):
    text = str(text or '').strip()
    if re.search(r'```|(?:翻译|translate|解释|讲解|如何实现|怎么实现|写.{0,6}代码)', text, re.I):
        return []
    if re.search(r'(?:不要|不需要|无需|不用|别|do not|don.t)\s*.{0,5}(?:搜索|联网|读取|search|browse|read)', text, re.I):
        return []
    urls = re.findall(r'https?://[^\s<>"\x27`]+', text)
    if urls and re.search(r'读|看|分析|总结|打开|浏览|read|summari[sz]e|browse|open', text, re.I):
        return [{'tool': 'read_web', 'args': {'url': u.rstrip('。，、；;!?！？）)')}} for u in urls[:2]]
    if re.search(r'(?:查看|查一下|读取|搜索|查找).{0,12}(?:我的账户|我的账号|我的邮箱|当前账户|我的资料|个人资料)',text):
        return [{'tool':'my_workspace'}]
    attachment = re.search(r'(?:读取|查看|读一下|read)\s*附件\s*[#＃]?\s*(\d+)', text, re.I)
    if attachment:
        return [{'tool': 'read_attachment', 'args': {'id': int(attachment[1])}}]
    record=re.search(r'(?:读取|查看|读一下)\s*(项目|任务|实验|公告|账目|报销|消息)\s*[#＃]?\s*(\d+)',text)
    if record:
        kind={'项目':'project','任务':'task','实验':'experiment','公告':'announcement','账目':'entry','报销':'claim','消息':'message'}[record[1]]
        return [{'tool':'read_record','args':{'kind':kind,'id':int(record[2])}}]
    if not re.search(r'搜索|搜一下|搜一搜|搜寻|查找|查一下|联网|search|look up|browse', text, re.I):
        return []
    if re.search(r'联网|网上|互联网|公开网页|官网|官方网站|\bweb\b',text,re.I):
        return [{'tool':'search_web','args':{'query':search_query(text)}}]
    internal = [('message', r'聊天|消息|讨论记录|公共讨论'), ('announcement', r'公告'), ('task', r'任务|待办'), ('experiment', r'实验'), ('entry', r'账目|账单'), ('claim', r'报销'), ('project', r'工作台|团队项目|项目资料')]
    for kind, pattern in internal:
        if re.search(pattern, text):
            return [{'tool': 'search_workspace', 'kind': kind}]
    return [{'tool': 'search_web', 'args': {'query': search_query(text)}}]


def from_history(history):
    users=[m.get('content','') for m in history if m.get('role')=='user']
    if not users: return []
    latest=str(users[-1]).strip()
    if re.fullmatch(r'[?？]+|继续[。！!]?|然后呢[?？]?|查到了吗[?？]?|结果呢[?？]?',latest):
        return next((requirements(text) for text in reversed(users[:-1][-5:]) if requirements(text)),[])
    return requirements(latest)


def pending(requirement, activity):
    for step in activity:
        if step.get('tool') != requirement['tool']:
            continue
        if requirement.get('kind') and step.get('kind') != requirement['kind']:
            continue
        expected = requirement.get('args', {})
        if 'url' in expected and step.get('url') != expected['url']:
            continue
        if 'kind' in expected and step.get('kind') != expected['kind']:
            continue
        if 'id' in expected and step.get('id') != expected['id']:
            continue
        if step.get('status') in ('success', 'empty', 'error'):
            return False  # Attempted failures are surfaced, never silently retried.
    return True


def promise_only(text):
    text = str(text or '').strip()
    if not text or len(text) > 180 or re.search(r'```|`|https?://|\[\d+\]', text):
        return False
    if re.search(r'找到|结果|如下|没有|失败|无法|不能|已经|根据|found|result|failed|cannot',text,re.I):
        return False
    return bool(re.fullmatch(r'(?:好的[，,。！!]?\s*|可以[，,。！!]?\s*|当然[，,。！!]?\s*)?(?:我(?:来|会|将|这就|马上|先|现在|帮你|为你|可以)|让我|正在|I(?:.ll| will)|Let me)\s*.{0,100}(?:搜|查|读|看|检索|search|read|check|look up|browse).{0,50}[。.!！…]*', text, re.I))


def outcome(name, args, value):
    if not isinstance(value, dict):
        value = {'error': '工具未返回有效结果。'}
    error = str(value.get('error') or '')[:500]
    pages = [v['source'] for v in value.get('results', []) if isinstance(v, dict) and isinstance(v.get('source'), dict)]
    if isinstance(value.get('source'), dict):
        pages.append(value['source'])
    if name in ('search_web', 'search_workspace'):
        count = len(value.get('results') or [])
    elif name in ('read_web', 'read_attachment'):
        count = int(bool(value.get('content')))
    else:
        count = int(bool(value and not error))
    status = 'error' if error else 'success' if count else 'empty'
    return {**{key: args[key] for key in ('query', 'kind', 'url', 'id') if key in args}, 'tool': name,
            'status': status, 'error': error, 'count': count, 'pages': pages}
