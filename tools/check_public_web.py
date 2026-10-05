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
page=read_web('https://docs.python.org/3/library/asyncio.html')
assert 'asyncio' in page['content'].lower()
print('PASS: real HTTPS page read with certificate and public address validation')
results=search_web('Python asyncio documentation')
assert results.get('results'),results.get('error','No search results')
print('PASS: live search returned',len(results['results']),'real public source links')
