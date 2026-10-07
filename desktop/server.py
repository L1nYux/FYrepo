"""Local desktop sidecar. The production application's routes stay unchanged."""
import json
import os
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ['WORKBENCH_DESKTOP_STATE']) / 'server'
STATE.mkdir(parents=True, exist_ok=True)
SOURCE = os.environ.get('WORKBENCH_DESKTOP_SOURCE_DATA')
if not (STATE / 'workbench.sqlite3').exists() and SOURCE:
    source = Path(SOURCE)
    if (source / 'workbench.sqlite3').is_file():
        with sqlite3.connect(source / 'workbench.sqlite3') as old, sqlite3.connect(STATE / 'workbench.sqlite3') as new:
            old.backup(new)
        if (source / 'private_uploads').is_dir():
            shutil.copytree(source / 'private_uploads', STATE / 'private_uploads', dirs_exist_ok=True)
secret_file = STATE / '.secret'
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(64), encoding='utf-8')
os.environ.update(WORKBENCH_SECRET_KEY=secret_file.read_text(encoding='utf-8'),
    WORKBENCH_DATA_DIR=str(STATE), WORKBENCH_DEBUG='1',
    WORKBENCH_ALLOWED_HOSTS='127.0.0.1,localhost', DJANGO_SETTINGS_MODULE='config.settings')
sys.path.insert(0, str(APP_ROOT))
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.urls import include, path
from wsgiref.simple_server import make_server, WSGIRequestHandler, WSGIServer
from socketserver import ThreadingMixIn

call_command('migrate', interactive=False, verbosity=0)
from desktop_auth import urlpatterns as auth_urls

urlpatterns = auth_urls + [path('', include('config.urls'))]
settings.ROOT_URLCONF = __name__
settings.WORKBENCH_DESKTOP = True


class LocalServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass  # No browser or token-bearing request log in the local prototype.


from django.core.wsgi import get_wsgi_application
from django.contrib.staticfiles.handlers import StaticFilesHandler
server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), LocalServer, QuietHandler)
from aihub.maintenance import start_local_scheduler
start_local_scheduler()
print(json.dumps({'desktop_ready': True, 'port': server.server_port}), flush=True)
server.serve_forever()
