"""Admission estimates only; the supplier's usage remains the billing authority."""
import hashlib
import json
import math
import os
import re
from functools import lru_cache
from django.conf import settings

URLS={name:'https://openaipublic.blob.core.windows.net/encodings/'+name+'.tiktoken'
      for name in ('o200k_base','cl100k_base')}
HASHES={'cl100k_base':'223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7',
        'o200k_base':'446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'}

@lru_cache(maxsize=2)
def encoding(name):
    # Deployment bundles the verified vocabulary; inference never downloads it.
    directory=settings.BASE_DIR/'vendor/tokenizers'
    file=directory/hashlib.sha1(URLS[name].encode()).hexdigest()
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=HASHES[name]:return None
    import tiktoken
    os.environ['TIKTOKEN_CACHE_DIR']=str(directory)
    try:return tiktoken.get_encoding(name)
    except (OSError,ValueError):return None

def default_output(model):
    return min(getattr(model,'default_output_tokens',4096),model.max_output_tokens)

def input_estimate(model,messages,tools):
    payload=(messages[0]['_billing_payload'] if len(messages)==1 and '_billing_payload' in messages[0] else
             {'messages':[{key:value for key,value in row.items() if not key.startswith('_')}
                         for row in messages],'tools':tools})
    text=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    size=len(text.encode('utf-8'))
    name=getattr(model,'tokenizer','auto')
    if name=='auto':
        identifier=model.model_id.lower().split('/')[-1]
        name=('o200k_base' if identifier.startswith(('gpt-4o','gpt-4.1','gpt-5','gpt-6','o1','o3','o4'))
              else 'cl100k_base' if identifier.startswith(('gpt-3.5','gpt-4')) else 'approximate')
    encoder=encoding(name) if name in URLS else None
    overhead=256+16*len(messages)+32*len(tools)
    if encoder is not None:
        token_count=sum(len(encoder.encode_ordinary(text[start:start+4096])) for start in range(0,len(text),4096))
        count=math.ceil(token_count*1.15)+overhead
        method=name
    elif name=='bytes':
        count=size+2048;method='bytes'
    else:
        # Unknown tokenizers: non-ASCII is estimated character by character;
        # English/code uses a conservative 2 bytes/token plus 25% headroom.
        ascii_count=sum(ord(char)<128 for char in text)
        count=math.ceil((ascii_count/2+len(text)-ascii_count)*1.25)+overhead
        method='approximate'
    images=sum(len(row.get('_images',[]))+sum(part.get('type')=='image_url' for part in row.get('_parts',[])) for row in messages)
    def media_count(value):
        if isinstance(value,list):return sum(media_count(item) for item in value)
        if isinstance(value,dict):return 1 if 'media_input' in value else sum(media_count(item) for item in value.values())
        return 0
    return {'bytes':size,'tokens':count+32768*(images+media_count(payload))+sum(row.get('_prior_tokens',0) for row in messages),'method':method}
