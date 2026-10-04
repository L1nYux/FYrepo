"""Public price sources, without sending provider credentials to third parties."""
import re
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlsplit
from django.core.cache import cache
from .network import json_request, text_request

DEEPSEEK_URL='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
ROUTER_URL='https://openrouter.ai/api/v1/models'
FX_URL='https://api.frankfurter.dev/v1/latest?base=USD&symbols=CNY'
AUTO='自动读取：'


def cached_fetch(key, loader, force=False):
    value=None if force else cache.get(key)
    if value is None:
        value=loader(); cache.set(key,value,3600)
    return value


def exchange_rate(force=False):
    def load():
        data=json_request(FX_URL,timeout=10,allow_query=True)
        value=Decimal(str(data['rates']['CNY']))
        if not value.is_finite() or not 0<value<100: raise ValueError('Invalid exchange rate')
        return {'rate':str(value),'day':data['date'],'source':FX_URL}
    return cached_fetch('pool-usd-cny',load,force)


class PriceTable(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.sup=False
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=''
        elif tag=='sup': self.sup=True
        elif tag=='br' and self.cell is not None: self.cell+=' '
    def handle_endtag(self,tag):
        if tag=='sup': self.sup=False
        elif tag in ('td','th') and self.cell is not None:
            self.row.append(self.cell.strip()); self.cell=None
        elif tag=='tr' and self.row is not None:
            self.rows.append(self.row); self.row=None
    def handle_data(self,data):
        if self.cell is not None and not self.sup: self.cell+=data


def deepseek_prices(force=False):
    def load():
        parser=PriceTable(); parser.feed(text_request(DEEPSEEK_URL))
        identifiers=None; rates=[]
        for row in parser.rows:
            if row and row[0]=='模型':
                identifiers=[s for s in row[1:] if re.fullmatch(r'deepseek-[a-z0-9-]+',s)]
            # Use peak prices for conservative estimates; don't guess public holiday schedules.
            if identifiers and '高峰时段' in row:
                tail=row[row.index('高峰时段')+1:]
                if len(tail)!=len(identifiers): raise ValueError('Price table layout changed')
                values=[]
                for text in tail:
                    match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*元\s*',text)
                    if not match: raise ValueError('Price table unit changed')
                    values.append(match.group(1))
                rates.append(values)
        if not identifiers or len(rates)!=3: raise ValueError('Official price table not recognized')
        result={}
        for index,identifier in enumerate(identifiers):
            result[identifier]={'currency':'CNY','cached_rate':rates[0][index],
                'input_rate':rates[1][index],'cache_write_rate':rates[1][index],
                'output_rate':rates[2][index],'cny_exchange_rate':'1',
                'source':AUTO+'DeepSeek 官方高峰价（保守估算；低峰实际费用可能更低） '+DEEPSEEK_URL}
        # Only aliases explicitly documented on the official page are mapped.
        if 'deepseek-flash' in result:
            for alias in ('deepseek-v4-flash','deepseek-v4-flash-vision-exp'):
                result[alias]=result['deepseek-flash']
        return result
    return cached_fetch('pool-deepseek-prices',load,force)


def automatic_price(provider, identifier, force=False):
    host=urlsplit(provider.base_url).hostname
    if host=='api.deepseek.com': return deepseek_prices(force).get(identifier)
    if host=='openrouter.ai':
        from .discovery import listed_price
        data=cached_fetch('pool-router-prices',lambda:json_request(ROUTER_URL,timeout=12),force)
        row=next((r for r in data.get('data',[]) if r.get('id')==identifier),None)
        if row:
            value=listed_price(provider,row)
            if value:
                fx=exchange_rate(force)
                return {**value,'cny_exchange_rate':fx['rate'],'source':value['source']+'；汇率 '+fx['day']+' '+FX_URL}
    from .vendor_prices import source_info, official_prices
    info=source_info(provider)
    if info['supported'] and info['vendor']!='existing':
        key=''
        from .vendor_prices import WORKSPACE_HOST
        if WORKSPACE_HOST.fullmatch(host or ''):
            from .service import provider_key
            key=provider_key(provider)
        value=official_prices(provider,key=key,force=force).get(identifier.lower())
        if value and value['currency']=='USD':
            try: fx=exchange_rate(force)
            except Exception:
                from .vendor_prices import PriceUnavailable
                raise PriceUnavailable('美元单价已读取，但人民币汇率读取失败；已有价格保留，可稍后重试或手动填写单价和汇率。') from None
            value={**value,'cny_exchange_rate':fx['rate'],'source':value['source']+'；汇率 '+fx['day']}
        return value
    return None


def enrich_catalog(provider, rows, key=''):
    """Price lookup failure doesn't discard a valid connection or invent a free model."""
    note=''; fx=None; host=urlsplit(provider.base_url).hostname
    if host=='api.deepseek.com':
        try:
            prices=deepseek_prices()
            for row in rows: row['price']=prices.get(row['id'])
        except Exception:
            note='官方价格暂时读取失败；保留已保存价格，未定价模型可只补两项单价。'
    from .vendor_prices import source_info, official_prices
    info=source_info(provider)
    if info['supported'] and info['vendor']!='existing':
        try:
            prices=official_prices(provider,key=key)
            for row in rows: row['price']=prices.get(row['id'].lower())
            note=info['note']+' 阶梯/模式差异按最高档保守估算；官方未列出的型号保留手动登记。'
        except Exception:
            note='官方价格暂时读取失败；已有价格保留，可点击自动读取重试或手动登记。'
    elif not info['supported']:
        note=info['note']
    if any(r.get('price',{}).get('currency')=='USD' for r in rows if r.get('price')):
        try:
            fx=exchange_rate()
            for row in rows:
                if row.get('price') and row['price']['currency']=='USD':
                    row['price']['cny_exchange_rate']=fx['rate']
                    row['price']['source']+='；汇率 '+fx['day']+' '+FX_URL
        except Exception:
            note+=' 汇率暂时读取失败，可在高级设置补充一次汇率。'
    return note,fx
