"""Render public JavaScript pages in a disposable, credential-free Chromium.

Every HTTP request is fulfilled by the DNS-pinned reader. Chromium's proxy is
deliberately unreachable: any traffic bypassing routing has no network path.
"""
import time
import threading
from contextlib import suppress
import logging
from django.conf import settings
from django.core.exceptions import ValidationError

CAPACITY=threading.BoundedSemaphore(2)
logger=logging.getLogger(__name__)


def render(url, initial=None):
    if not getattr(settings, 'WORKBENCH_WEB_RENDER', True):
        raise ValidationError('此页面需要 JavaScript，网页渲染尚未启用。')
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError:
        raise ValidationError('此页面需要 JavaScript，请安装网页渲染运行环境。') from None
    from .web_tools import fetch_public, resolve_public
    resolve_public(url)
    if not CAPACITY.acquire(blocking=False):
        raise ValidationError('网页浏览正在处理其他请求，请稍后重试。')
    started=time.monotonic(); requests=0; downloaded=0; blocks=0
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True, chromium_sandbox=True,
                proxy={'server':'http://127.0.0.1:9'},
                args=['--proxy-bypass-list=<-loopback>', '--disable-background-networking',
                      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
            try:
                context=browser.new_context(service_workers='block', accept_downloads=False,
                    permissions=[], locale='zh-CN', viewport={'width':1280,'height':800})
                # A matched socket has no upstream connection unless the handler
                # calls connect_to_server(). Discard its messages locally; making
                # a synchronous close call inside this callback can deadlock the
                # Playwright driver on Windows.
                context.route_web_socket('**/*', lambda route: route.on_message(lambda message: None))
                def route_request(route):
                    nonlocal requests, downloaded, blocks
                    request=route.request; requests+=1
                    if requests>40 or time.monotonic()-started>22 or downloaded>12*1024*1024 or request.method!='GET' or request.resource_type in ('image','media','font'):
                        blocks+=1; route.abort(); return
                    try:
                        resolve_public(request.url)
                        if initial and request.url==url and requests==1:
                            final, mime, raw=initial
                        else:
                            final, mime, raw=fetch_public(request.url)
                        downloaded+=len(raw)
                        if final!=request.url:
                            # Browser navigation must reflect the verified final URL.
                            route.fulfill(status=302,headers={'location':final}); return
                        route.fulfill(status=200, content_type=mime or 'application/octet-stream', body=raw,
                                      headers={'access-control-allow-origin':'*'})
                    except (ValidationError, BrowserError):
                        blocks+=1; route.abort()
                context.route('**/*', route_request)
                page=context.new_page()
                page.on('popup', lambda popup: popup.close())
                page.on('download', lambda download: download.cancel())
                page.goto(url, wait_until='domcontentloaded', timeout=24000)
                # A short bounded hydration window, not an unbounded network-idle wait.
                page.wait_for_timeout(1200)
                text=page.locator('body').inner_text(timeout=3000).strip()
                if not text or len(text)<30:
                    raise ValidationError('页面未提供可读取正文，可能需要登录或触发了网站验证。')
                return {'url':page.url,'title':page.title()[:180], 'content':text[:14000],
                        'truncated':len(text)>14000,'read_mode':'browser','blocked_requests':blocks}
            finally:
                with suppress(Exception): browser.close()
    except ValidationError:
        raise
    except BrowserError as error:
        message = str(error)
        if any(marker in message for marker in ('No usable sandbox', 'Failed to move to new namespace', 'SUID sandbox', 'Operation not permitted')):
            reason = 'Chromium 沙盒权限被系统拒绝，请检查用户命名空间与 AppArmor 配置。'
        elif "Executable doesn't exist" in message:
            reason = 'Chromium 尚未安装，请先准备网页读取运行环境。'
        else:
            reason = '网页渲染未完成，请检查 Chromium 运行环境或换一个来源。'
        # Classify operational failures without logging source URLs or page text.
        logger.warning('Public browser failure: %s', reason)
        raise ValidationError(reason) from None
    except Exception as error:
        logger.warning('Public browser driver failed: %s',type(error).__name__)
        raise ValidationError('网页浏览进程未完成，请重试或换一个来源。') from None
    finally:
        CAPACITY.release()
