"""Resolve synthetic proxy DNS through fixed, TLS-verified public resolvers.

This never makes a reserved address connectable. A separate real public DNS
answer is required; local/private answers are still rejected by resolve_public.
"""
import hashlib
import http.client
import ipaddress
import json
from urllib.parse import urlencode
from django.core.cache import cache
from django.core.exceptions import ValidationError


def resolve(hostname):
    from .web_tools import PinnedHTTP
    key='public-dns:'+hashlib.sha256(hostname.encode()).hexdigest()
    cached=cache.get(key)
    if cached:return cached
    resolvers=[('cloudflare-dns.com',['1.1.1.1','1.0.0.1'],'/dns-query'),
               ('dns.google',['8.8.8.8','8.8.4.4'],'/resolve')]
    for host, addresses, path in resolvers:
        connection=PinnedHTTP(host,443,addresses,True)
        try:
            connection.request('GET',path+'?'+urlencode({'name':hostname,'type':'A','edns_client_subnet':'0.0.0.0/0'}),
                               headers={'Accept':'application/dns-json'})
            response=connection.getresponse()
            if response.status!=200:continue
            raw=response.read(65537)
            if len(raw)>65536:continue
            value=json.loads(raw)
            if value.get('Status')!=0:continue
            answers=list(dict.fromkeys(str(ipaddress.IPv4Address(row['data']))
                for row in value.get('Answer',[]) if row.get('type')==1))
            if answers:
                cache.set(key,answers,30);return answers
        except (OSError,ValueError,TypeError,KeyError,http.client.HTTPException):
            continue
        finally:connection.close()
    raise ValidationError('当前网络返回代理占位地址，未取得可验证的公网 DNS 结果。')
