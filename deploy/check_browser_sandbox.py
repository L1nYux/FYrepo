"""Probe installed Chromium sandbox with inline content and no network access."""
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, Error

for name in ('kernel/apparmor_restrict_unprivileged_userns', 'kernel/unprivileged_userns_clone', 'user/max_user_namespaces'):
    path = Path('/proc/sys') / name
    if path.is_file(): print(name + '=' + path.read_text().strip(), flush=True)
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, chromium_sandbox=True,
            proxy={'server': 'http://127.0.0.1:9'}, args=['--proxy-bypass-list=<-loopback>'])
        try:
            page = browser.new_page()
            page.set_content('<html><body>Isolated sandbox startup probe</body></html>')
            assert page.locator('body').inner_text() == 'Isolated sandbox startup probe'
            print('PASS: Chromium sandbox startup ' + browser.version, flush=True)
        finally: browser.close()
except Error as error:
    # This probe contains no URLs, user content, credentials or real connections.
    detail = str(error)
    if len(detail) > 3400: detail = detail[:2300] + '\n…\n' + detail[-1000:]
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print('::error title=Chromium sandbox startup::' + detail.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A'))
    else: print(detail, file=sys.stderr)
    raise SystemExit(1)
