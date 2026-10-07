"""Official public price sources. Never send keys to a documentation site.

The pool uses fixed rates for estimates, so multiple length/mode tiers use their
highest rates with an explicit explanation. No account discounts are inferred.
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlencode
from django.core.cache import cache
from .network import json_request, text_request

QWEN_URL = 'https://help.aliyun.com/zh/model-studio/model-pricing'
GLM_URL = 'https://docs.bigmodel.cn/cn/guide/start/pricing'
MINIMAX_CN_URL = 'https://platform.minimax.cn/docs/guides/pricing-paygo'
MINIMAX_US_URL = 'https://platform.minimax.io/docs/guides/pricing-paygo'
WORKSPACE_HOST = re.compile(r'[a-z0-9-]{1,80}\.cn-beijing\.maas\.aliyuncs\.com\Z')
MINIMAX_HOSTS = {'api.minimaxi.com', 'api.minimax.cn', 'api.minimax.io'}
AUTO = '自动读取：'


class PriceUnavailable(ValueError):
    """An actionable, safe error; never include an upstream response or key."""


def source_info(provider):
    address = urlsplit(provider.base_url)
    host = address.hostname or ''
    if host in MINIMAX_HOSTS:
        return {'supported': True, 'vendor': 'minimax', 'url': MINIMAX_US_URL if host == 'api.minimax.io' else MINIMAX_CN_URL,
                'note': '读取 MiniMax 官方按量价；M Plan / Token Plan 的实际消耗以订阅额度为准。'}
    if host == 'open.bigmodel.cn':
        return {'supported': True, 'vendor': 'glm', 'url': GLM_URL,
                'note': '读取智谱官方按量价；Coding Plan 的实际消耗以订阅额度为准。'}
    if host == 'dashscope.aliyuncs.com' or WORKSPACE_HOST.fullmatch(host):
        return {'supported': True, 'vendor': 'qwen', 'url': QWEN_URL,
                'note': '读取百炼北京地域、中国内地部署的官方价；其他厂商模型也使用百炼渠道价。'}
    if host in ('api.deepseek.com', 'openrouter.ai'):
        return {'supported': True, 'vendor': 'existing', 'url': '', 'note': '已接入自动价格来源。'}
    note = '这个连接尚未接入可靠的自动价格来源，可手动登记单价。'
    if host.endswith('.aliyuncs.com') and ('dashscope' in host or '.maas.' in host):
        note = '此百炼地域或套餐地址尚未接入自动价格，请按该连接的官方价格手动登记。'
    return {'supported': False, 'vendor': '', 'url': '', 'note': note}


def compact(value):
    value = re.sub(r'~~.*?~~', '', value)
    value = re.sub(r'<[^>]*>', ' ', value)
    return re.sub(r'\s+', '', value.replace('**', '').replace('\\', '')).strip()


def rate(value):
    value = compact(value)
    if value in ('免费', '限时免费', 'Free', 'free'):
        return Decimal('0')
    # Both Markdown strikethrough and an explicit current discount are supported.
    match = re.fullmatch(r'原价(\d+(?:\.\d+)?)元[（(]限时(\d+(?:\.\d+)?)折[）)]', value)
    if match:
        result = Decimal(match[1]) * Decimal(match[2]) / 10
    else:
        match = re.fullmatch(r'\$?(\d+(?:\.\d+)?)(?:元|/Mtokens)?', value, re.I)
        if not match:
            raise ValueError('Unrecognized price')
        result = Decimal(match[1])
    if not result.is_finite() or not 0 <= result <= 100000:
        raise ValueError('Invalid price')
    return result


def combine(rows, currency, url, label):
    result = {}
    for identifier, values in rows:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,159}', identifier):
            continue
        entry = result.setdefault(identifier.lower(), [])
        entry.append(values)
    prices = {}
    for identifier, entries in result.items():
        highest = {name: str(max(entry[name] for entry in entries)) for name in entries[0]}
        distinct = len({tuple(entry.items()) for entry in entries}) > 1
        note = '；阶梯或模式价格按最高档保守估算' if distinct else ''
        prices[identifier] = {**highest, 'currency': currency, 'cny_exchange_rate': '1' if currency == 'CNY' else '',
                              'source': AUTO + label + note + '；按量参考，赠送/订阅额度及促销以厂商账单为准 ' + url}
    return prices


def markdown_prices(document, vendor, currency, url):
    rows, header = [], None
    skip_priority = False
    for line in document.splitlines():
        if '<Tab ' in line:
            skip_priority = bool(re.search(r'title="(?:优先|Priority)', line, re.I))
        elif '</Tab>' in line:
            skip_priority = False
        if skip_priority or not line.strip().startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        clean = [compact(cell) for cell in cells]
        if clean and clean[0] in ('模型名称', '模型', 'Model'):
            header = clean
            # Accept only text token rates, not storage per hour or media rates.
            if vendor == 'glm' and not any('输入单价（元/百万Tokens）' in cell for cell in clean):
                header = None
            if vendor == 'minimax' and not any(('元/百万tokens' in cell or cell.lower() == 'input') for cell in clean):
                header = None
            continue
        if not header or len(cells) != len(header):
            continue
        model = re.match(r'\s*(?:\*\*)?((?:GLM|MiniMax)-[a-zA-Z0-9.-]+)', cells[0], re.I)
        if not model:
            continue
        try:
            input_index = next(i for i, cell in enumerate(header) if '输入' in cell or cell.lower() == 'input')
            output_index = next(i for i, cell in enumerate(header) if '输出' in cell or cell.lower() == 'output')
            input_rate, output_rate = rate(cells[input_index]), rate(cells[output_index])
            cached_index = next((i for i, cell in enumerate(header) if '缓存命中' in cell or '缓存读取' in cell or 'cachingread' in cell.lower()), None)
            write_index = next((i for i, cell in enumerate(header) if '缓存写入' in cell or 'cachingwrite' in cell.lower()), None)
            cached = input_rate if cached_index is None or compact(cells[cached_index]) == '不支持' else rate(cells[cached_index])
            write = input_rate if write_index is None else rate(cells[write_index])
            rows.append((model[1], {'input_rate': input_rate, 'output_rate': output_rate, 'cached_rate': cached, 'cache_write_rate': write}))
        except (ValueError, StopIteration, InvalidOperation):
            continue
    if not rows:
        raise PriceUnavailable('官方价目表格式无法识别，已有价格保留，请稍后重试或手动登记。')
    return combine(rows, currency, url, '智谱官方价目表' if vendor == 'glm' else 'MiniMax 官方标准服务价目表')


class BailianTables(HTMLParser):
    """Read rendered tables, expanding rowspans and ignoring embedded scripts."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.ignore = 0
        self.heading = None
        self.region = ''
        self.table = None
        self.row = None
        self.cell = None
        self.spans = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 's', 'del', 'sup'):
            self.ignore += 1
        if self.ignore:
            return
        if re.fullmatch('h[2-5]', tag):
            self.heading = [tag, '']
        elif tag == 'table':
            self.table = []; self.spans = {}
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('th', 'td') and self.row is not None:
            self.cell = ['', min(int(attrs.get('rowspan', 1)), 100), min(int(attrs.get('colspan', 1)), 20)]
        elif tag in ('p', 'br', 'blockquote') and self.cell is not None:
            self.cell[0] += '\n'

    def handle_data(self, data):
        if self.ignore:
            return
        if self.heading is not None:
            self.heading[1] += data
        if self.cell is not None:
            self.cell[0] += data

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 's', 'del', 'sup'):
            self.ignore = max(0, self.ignore - 1); return
        if self.ignore:
            return
        if self.heading and tag == self.heading[0]:
            title = compact(self.heading[1])
            if title in ('华北2（北京）', '新加坡', '美国（弗吉尼亚）', '德国（法兰克福）', '日本（东京）', '中国香港'):
                self.region = title
            elif tag in ('h2', 'h3'):
                self.region = ''
            self.heading = None
        elif tag in ('th', 'td') and self.cell is not None:
            self.row.append(tuple(self.cell)); self.cell = None
        elif tag == 'tr' and self.row is not None:
            expanded = []; column = 0
            def carried():
                nonlocal column
                while column in self.spans:
                    value, remaining = self.spans[column]
                    expanded.append(value)
                    if remaining == 1: del self.spans[column]
                    else: self.spans[column] = (value, remaining - 1)
                    column += 1
            for text, rowspan, colspan in self.row:
                carried()
                for _ in range(colspan):
                    expanded.append(text.strip())
                    if rowspan > 1: self.spans[column] = (text.strip(), rowspan - 1)
                    column += 1
            carried()
            self.table.append(expanded); self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append((self.region, self.table)); self.table = None


def bailian_html_prices(document):
    parser = BailianTables(); parser.feed(document)
    rows = []
    for region, table in parser.tables:
        if region != '华北2（北京）' or not table:
            continue
        header = [compact(cell) for cell in table[0]]
        # A Beijing global deployment is a different tariff; do not merge it.
        if any('服务部署范围' in cell for cell in header):
            continue
        inputs = [i for i, cell in enumerate(header) if '输入单价' in cell and '每百万' in cell and '缓存' not in cell]
        outputs = [i for i, cell in enumerate(header) if '输出单价' in cell and '每百万' in cell]
        if not inputs or not outputs:
            continue
        for cells in table[1:]:
            if len(cells) != len(header):
                continue
            match = re.match(r'\s*([a-zA-Z0-9][a-zA-Z0-9/_.-]*)', cells[0])
            if not match:
                continue
            try:
                input_rate = max(rate(cells[i]) for i in inputs)
                output_rate = max(rate(cells[i]) for i in outputs)
                rows.append((match[1], {'input_rate': input_rate, 'output_rate': output_rate,
                                       'cached_rate': input_rate, 'cache_write_rate': input_rate}))
            except (ValueError, InvalidOperation):
                continue
    if not rows:
        raise PriceUnavailable('百炼官方价目表格式无法识别，已有价格保留，请稍后重试或手动登记。')
    return combine(rows, 'CNY', QWEN_URL, '百炼北京·中国内地官方价目表（缓存暂按普通输入估算）')


def bailian_api_prices(data):
    if data.get('success') is not True or not isinstance(data.get('output', {}).get('models'), list):
        raise ValueError('Invalid catalog')
    rows = []
    for model in data['output']['models']:
        if not isinstance(model, dict) or not isinstance(model.get('model'), str):
            continue
        for tier in model.get('prices', []):
            values = {}
            for item in tier.get('prices', []):
                if item.get('price_unit') not in ('每百万tokens', '每百万Tokens'):
                    continue
                field = {'input_token': 'input_rate', 'output_token': 'output_rate'}.get(item.get('type'))
                if field:
                    try: values[field] = rate(str(item.get('price')))
                    except (ValueError, InvalidOperation): pass
            if set(values) == {'input_rate', 'output_rate'}:
                rows.append((model['model'], {**values, 'cached_rate': values['input_rate'], 'cache_write_rate': values['input_rate']}))
    return combine(rows, 'CNY', 'https://help.aliyun.com/zh/model-studio/list-models', '百炼北京·中国内地模型定价接口（缓存暂按普通输入估算）')


def cached_source(name, loader, force=False):
    key = 'pool-official-prices-v1-' + name
    value = None if force else cache.get(key)
    if value is None:
        value = loader(); cache.set(key, value, 3600)
    return value


def official_prices(provider, key='', force=False):
    info = source_info(provider)
    if not info['supported'] or info['vendor'] == 'existing':
        raise PriceUnavailable(info['note'])
    vendor = info['vendor']
    if vendor in ('glm', 'minimax'):
        currency = 'USD' if info['url'] == MINIMAX_US_URL else 'CNY'
        return cached_source(info['url'], lambda: markdown_prices(text_request(info['url'] + '.md'), vendor, currency, info['url']), force)
    host = urlsplit(provider.base_url).hostname or ''
    # Only an explicitly configured Beijing workspace receives the saved key.
    # Existing legacy connections can read the public tariff without extra setup.
    if WORKSPACE_HOST.fullmatch(host) and key:
        def load_api():
            url = 'https://' + host + '/api/v1/models?'
            result = {}
            for page in range(1, 6):
                data = json_request(url + urlencode({'page_no': page, 'page_size': 100, 'service_site': 'asia-pacific-china'}),
                                    headers={'Authorization': 'Bearer ' + key}, timeout=12, allow_query=True)
                result.update(bailian_api_prices(data))
                if page * 100 >= int(data['output'].get('total', 0)):
                    break
            if not result: raise ValueError('No token prices')
            return result
        try:
            fingerprint = hashlib.sha256((host + '\0' + key).encode()).hexdigest()
            return cached_source(fingerprint, load_api, force)
        except Exception:
            pass  # Public tariff fallback is explicitly identified in the source.
    return cached_source('bailian-beijing', lambda: bailian_html_prices(text_request(QWEN_URL)), force)
