"""Vendor-matched public reference prices; never apply an unrelated model's rate."""
import re
from decimal import Decimal
from urllib.parse import urlsplit
from .network import json_request
from .automatic_prices import cached_fetch,exchange_rate,AUTO

URL='https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json'
HOSTS={'api.openai.com':'openai','api.anthropic.com':'anthropic','generativelanguage.googleapis.com':'gemini'}

def reference_price(provider,identifier,force=False):
    vendor=HOSTS.get(urlsplit(provider.base_url).hostname)
    if not vendor:return None
    catalog=cached_fetch('pool-public-model-prices',lambda:json_request(URL,timeout=15),force)
    row=next((catalog[name] for name in (identifier,vendor+'/'+identifier) if name in catalog
              and catalog[name].get('litellm_provider')==vendor),None)
    if not row or row.get('mode') not in ('chat','embedding'):return None
    def rate(key,default=None):
        value=row.get(key,default)
        if value is None:return None
        result=Decimal(str(value))*1000000
        if not result.is_finite() or result<0 or result>100000:raise ValueError('Invalid reference rate')
        return str(result.quantize(Decimal('.000001')))
    incoming=rate('input_cost_per_token');outgoing=rate('output_cost_per_token',0 if row['mode']=='embedding' else None)
    if incoming is None or outgoing is None:return None
    value={'currency':'USD','input_rate':incoming,'output_rate':outgoing,
           'cached_rate':rate('cache_read_input_token_cost',row['input_cost_per_token']),
           'cache_write_rate':rate('cache_creation_input_token_cost',row['input_cost_per_token']),
           'cny_exchange_rate':exchange_rate(force)['rate'],
           'source':AUTO+'公开参考价（LiteLLM；实际供应商账单为准） '+URL,'tiers':[]}
    thresholds=sorted({int(match.group(1))*1000 for key in row if (match:=re.fullmatch(r'input_cost_per_token_above_(\d+)k_tokens',key))})
    for threshold in thresholds:
        suffix='_above_'+str(threshold//1000)+'k_tokens'
        value['tiers'].append({'above_tokens':threshold,'input_rate':rate('input_cost_per_token'+suffix),
            'output_rate':rate('output_cost_per_token'+suffix,row.get('output_cost_per_token',0)),
            'cached_rate':rate('cache_read_input_token_cost'+suffix,row.get('cache_read_input_token_cost',row['input_cost_per_token'])),
            'cache_write_rate':rate('cache_creation_input_token_cost'+suffix,row.get('cache_creation_input_token_cost',row['input_cost_per_token']))})
    return value
