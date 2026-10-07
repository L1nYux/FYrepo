"""Small bounded JSON transport; credentials never follow redirects."""
import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.core.exceptions import ValidationError


class TransportError(Exception):
    def __init__(self, code, uncertain=False):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


def validate_url(value, allow_query=False):
    p = urlsplit(value)
    loopback = p.hostname in ('localhost','127.0.0.1','::1')
    if not p.hostname or p.username or p.password or (p.query and not allow_query) or p.fragment:
        raise ValidationError('请填写不含凭证、参数或片段的接口地址。')
    if p.scheme != 'https' and not (settings.DEBUG and loopback and p.scheme == 'http'):
        raise ValidationError('接口和价格源需要 HTTPS；开发环境允许本机 HTTP。')
    return value.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def _request(url, headers=None, body=None, allow_query=False):
    validate_url(url, allow_query=allow_query)
    host=urlsplit(url).hostname
    if not (settings.DEBUG and host in ('localhost','127.0.0.1','::1')):
        try:
            addresses=socket.getaddrinfo(host, None)
            def permitted(address):
                ip=ipaddress.ip_address(address)
                # Local proxy Fake-IP DNS uses this benchmark range. Keep private/LAN blocks intact.
                fake_ip=(getattr(settings,'WORKBENCH_DESKTOP',False) and ip.version==4
                         and ip in ipaddress.ip_network('198.18.0.0/15'))
                return ip.is_global or fake_ip
            if any(not permitted(item[4][0]) for item in addresses):
                raise TransportError('private_endpoint')
        except socket.gaierror:
            raise TransportError('dns_error')
    req=Request(url, headers={'Accept':'application/json', **(headers or {})},
        data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None)
    return req


def raw_request(url, headers=None, body=None, timeout=45, allow_query=False):
    req = _request(url, headers, body, allow_query)
    try:
        with build_opener(NoRedirect).open(req,timeout=timeout) as response:
            raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024: raise TransportError('response_too_large', body is not None)
            return raw
    except HTTPError as error:
        # 4xx denotes rejected requests; 5xx can follow an upstream billable call.
        raise TransportError('http_'+str(error.code), body is not None and error.code>=500) from None
    except (URLError,TimeoutError,OSError):
        raise TransportError('connection_interrupted', body is not None) from None


def json_request(url, headers=None, body=None, timeout=45, allow_query=False):
    try:
        result=json.loads(raw_request(url,headers,body,timeout,allow_query))
        if not isinstance(result,dict): raise TransportError('invalid_response', body is not None)
        return result
    except (ValueError,UnicodeDecodeError):
        raise TransportError('invalid_json', body is not None) from None


def text_request(url, timeout=12):
    return raw_request(url,{'Accept':'text/html'},timeout=timeout).decode('utf-8')


def json_events(url, headers, body, timeout=45):
    """Bounded SSE, with one-request JSON fallback; never retry a billable POST."""
    req = _request(url, {'Accept':'text/event-stream', **headers}, body)
    total = 0
    started = time.monotonic()
    try:
        with build_opener(NoRedirect).open(req, timeout=timeout) as response:
            if 'application/json' in response.headers.get('Content-Type',''):
                raw = response.read(8*1024*1024+1)
                if len(raw) > 8*1024*1024: raise TransportError('response_too_large', True)
                value = json.loads(raw)
                if not isinstance(value, dict): raise TransportError('invalid_response', True)
                yield value
                return
            data = []
            while True:
                line = response.readline(1024*1024+1)
                total += len(line)
                if total > 8*1024*1024 or len(line) > 1024*1024:
                    raise TransportError('response_too_large', True)
                if time.monotonic()-started > 150:
                    raise TransportError('stream_timeout', True)
                if line in (b'\n',b'\r\n',b''):
                    if data:
                        payload = '\n'.join(data)
                        data = []
                        if payload == '[DONE]': return
                        value = json.loads(payload)
                        if not isinstance(value,dict): raise TransportError('invalid_response', True)
                        yield value
                    if not line: return
                elif line.startswith(b'data:'):
                    data.append(line[5:].decode('utf-8').strip())
    except HTTPError as error:
        raise TransportError('http_'+str(error.code), error.code>=500) from None
    except (URLError,TimeoutError,OSError):
        raise TransportError('connection_interrupted', True) from None
    except (ValueError,UnicodeDecodeError):
        raise TransportError('invalid_stream', True) from None
