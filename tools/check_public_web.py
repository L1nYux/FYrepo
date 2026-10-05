"""Opt-in live public web probe; no model calls or provider credentials."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
os.environ.setdefault('WORKBENCH_SECRET_KEY','isolated-public-web-probe')
import django
django.setup()
from aihub.web_tools import read_web,search_web
from django.core.exceptions import ValidationError
failed=False
try:
    page=read_web('https://docs.python.org/3/library/asyncio.html')
    if 'asyncio' not in page['content'].lower():raise ValidationError('Public page returned unrelated content')
    print('PASS: real HTTPS page read with certificate and public address validation')
except ValidationError as error:
    failed=True
    message='Public page read: '+' '.join(error.messages)
    print('::error::'+message.replace('%','%25').replace('\n','%0A').replace('\r','%0D'))
results=search_web('Python asyncio documentation')
if not results.get('results'):
    failed=True
    message='Public search: '+results.get('error','No search results')
    print('::error::'+message.replace('%','%25').replace('\n','%0A').replace('\r','%0D'))
else:print('PASS: live search returned',len(results['results']),'real public source links')
if failed:raise SystemExit(1)
