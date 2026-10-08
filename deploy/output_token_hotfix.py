"""Standalone, backed-up emergency patch for the 0.4.2/0.4.4 API gateway.

Release packaging embeds exact source hashes and changed files into BUNDLE.
No model inference or supplier API call is made by this installer.
"""
import argparse
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import uuid

BUNDLE = None  # Replaced in the standalone release asset, not in repository source.

DATABASE_TASK = r'''
import json, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from aihub.models import PoolModel
mode, explicit = sys.argv[1:]
rows = PoolModel.all_objects.filter(enabled=True, provider__enabled=True,
    workspace__kind='team', workspace__active=True, workspace__team__active=True)
spaces = sorted(set(rows.values_list('workspace_id', flat=True)))
if explicit:
    selected = int(explicit)
    if selected not in spaces: raise SystemExit('The chosen workspace has no enabled team models.')
elif len(spaces) == 1: selected = spaces[0]
else: raise SystemExit('Multiple/no active API workspaces: '+str(spaces)+'. Run with --workspace ID to select one. No changes made.')
rows = rows.filter(workspace_id=selected)
fields = ['id','model_id','workspace_id','max_output_tokens']
before = list(rows.order_by('pk').values(*fields))
if mode == 'apply':
    call_command('migrate','aihub',verbosity=0,interactive=False)
    with transaction.atomic():
        locked = list(rows.select_for_update().filter(max_output_tokens__in=[2048,8192]).values_list('pk',flat=True))
        changed = PoolModel.all_objects.filter(pk__in=locked,max_output_tokens__in=[2048,8192]).update(max_output_tokens=32768)
    after = list(rows.order_by('pk').values(*fields))
    if any(r['max_output_tokens'] != 32768 for r in after if r['id'] in locked):
        raise SystemExit('Output configuration update did not complete.')
else: changed = 0; after = before
db = settings.DATABASES['default']
if db['ENGINE'] != 'django.db.backends.sqlite3': raise SystemExit('This installer requires the deployed SQLite database.')
print(json.dumps({'workspace':selected,'database':str(db['NAME']),'models':before,'after':after,'changed':changed},ensure_ascii=False))
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def active(unit):
    return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode == 0


def database_task(current, mode, workspace):
    # systemd loads the service's production environment without printing secrets.
    result = run('systemd-run','--quiet','--wait','--pipe','--collect',
        '--unit=zhiyu-output-'+uuid.uuid4().hex[:12],
        '--property=User=workbench','--property=Group=workbench',
        '--property=WorkingDirectory='+str(current),
        '--property=EnvironmentFile=/etc/research-workbench.env',
        str(current/'.venv/bin/python'),'-c',DATABASE_TASK,mode,str(workspace or ''),
        text=True,capture_output=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def replace(path, data, owner):
    handle, temporary = tempfile.mkstemp(prefix='.output-fix-',dir=path.parent)
    try:
        with os.fdopen(handle,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o644);os.chown(temporary,*owner)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=int)
    args = parser.parse_args()
    if os.geteuid() != 0: raise SystemExit('Run with sudo python3.')
    if BUNDLE is None: raise SystemExit('Use the packaged standalone hotfix from the release.')
    current = Path(subprocess.check_output(['systemctl','show','research-workbench',
        '-p','WorkingDirectory','--value'],text=True).strip())
    if (current.parent != Path('/opt/research-workbench-releases') or current.is_symlink()
        or current.resolve() != current or not current.is_dir()):
        raise SystemExit('Cannot confirm the running release directory; no changes made.')
    info = json.loads((current/'desktop/release-info.json').read_text())
    if info.get('version') not in BUNDLE['versions']:
        raise SystemExit('This hotfix supports server 0.4.2 or 0.4.4 only; no changes made.')
    env = Path('/etc/research-workbench.env')
    if not env.is_file() or env.is_symlink(): raise SystemExit('Missing production environment; no changes made.')
    original, payload, owners = {}, {}, {}
    for name, entry in BUNDLE['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'aihub':
            raise SystemExit('Invalid patch path.')
        target = current/relative
        if target.is_symlink() or not target.resolve().is_relative_to(current):
            raise SystemExit('Unexpected source symlink; no changes made.')
        data = base64.b64decode(entry['data'],validate=True)
        if sha(data) != entry['after']: raise SystemExit('Patch payload integrity failure.')
        ast.parse(data,filename=name)
        previous = target.read_bytes() if target.exists() else None
        expected = entry['before']
        if previous is None and None not in expected or previous is not None and sha(previous) not in expected+[entry['after']]:
            raise SystemExit('Installed source differs; no changes made: '+name)
        stat = (target if target.exists() else target.parent).stat()
        original[name] = previous; payload[name] = data; owners[name] = (stat.st_uid,stat.st_gid)
    if not active('research-workbench'): raise SystemExit('The application is not active; no changes made.')
    try: report = database_task(current,'report',args.workspace)
    except subprocess.CalledProcessError as error:
        raise SystemExit('Configuration lookup failed before changes:\n'+error.stderr) from None
    database = Path(report['database']).resolve()
    if database.parent != Path('/var/lib/research-workbench') or not database.is_file() or database.is_symlink():
        raise SystemExit('Unexpected database path; no changes made.')
    print('Selected API workspace:',report['workspace'],flush=True)
    for row in report['models']:
        print(str(row['id'])+' '+row['model_id']+' : '+str(row['max_output_tokens'])
            +(' -> 32768' if row['max_output_tokens'] in (2048,8192) else ' (keep)'),flush=True)
    backup = Path('/var/backups/research-workbench')/('output-hotfix-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,mode=0o700)
    (backup/'before.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for name, data in original.items():
        if data is not None:
            saved = backup/'source'/name; saved.parent.mkdir(parents=True,exist_ok=True); saved.write_bytes(data)
    units = ['research-workbench-prices.timer','research-workbench-gifts.timer','research-workbench-releases.timer',
        'research-workbench-prices.service','research-workbench-gifts.service','research-workbench-releases.service',
        'research-workbench.service']
    running = [unit for unit in units if active(unit)]
    stopped = []; replaced = []; db_saved = False
    try:
        for unit in running:
            run('systemctl','stop',unit); stopped.append(unit)
        with sqlite3.connect(str(database)) as source, sqlite3.connect(str(backup/'workbench.sqlite3')) as destination:
            source.backup(destination)
        db_saved = True
        for name, data in payload.items():
            if data != original[name]:
                replace(current/name,data,owners[name]); replaced.append(name)
        result = database_task(current,'apply',report['workspace'])
        run('systemctl','start','research-workbench.service')
        healthy = False
        for attempt in range(15):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/healthz/',timeout=4) as response:
                    healthy = json.load(response).get('status')=='ok'
                if healthy: break
            except Exception: pass
            time.sleep(1)
        if not healthy: raise RuntimeError('Application health did not recover.')
        (backup/'applied.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print('HOTFIX OK: '+str(result['changed'])+' models raised to 32768; truncation returns length.',flush=True)
        print('Backup: '+str(backup),flush=True)
    except Exception as error:
        subprocess.run(['systemctl','stop','research-workbench.service'])
        for name in reversed(replaced):
            if original[name] is None: (current/name).unlink()
            else: replace(current/name,original[name],owners[name])
        if db_saved:
            with sqlite3.connect(str(backup/'workbench.sqlite3')) as source, sqlite3.connect(str(database)) as destination:
                source.backup(destination)
        print('Hotfix failed; source and database restored. Backup: '+str(backup),flush=True)
        if isinstance(error,subprocess.CalledProcessError) and error.stderr: print(error.stderr,flush=True)
        raise
    finally:
        for unit in reversed(running):
            subprocess.run(['systemctl','start',unit],check=False)


if __name__ == '__main__':
    main()
