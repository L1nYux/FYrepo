"""Standalone, reversible long-document inference timeout patch.

Packaging embeds source hashes into BUNDLE. No billable inference is sent and
no historical call, budget, key or output-capacity setting is changed.
"""
import argparse
import ast
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request
import uuid

BUNDLE = None  # Replaced only in the standalone release asset.

AUDIT_TASK = r'''
import json,os,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.conf import settings
from django.utils import timezone
from aihub.models import Call
from aihub.providers import INFERENCE_TIMEOUT_SECONDS
recent=timezone.now()-timezone.timedelta(minutes=5)
calls=Call.all_objects.filter(experiment__number=sys.argv[1]).order_by('created_at')
fields=['id','workspace_id','model_id','model__model_id','user_id','created_at',
    'finished_at','latency_ms','status','error_code','provider_request_id',
    'reserved_cny','extra_reserved_cny','cost_cny','reconciled']
rows=list(calls.values(*fields))
db=settings.DATABASES['default']
print(json.dumps({'database':str(db['NAME']),'database_engine':db['ENGINE'],
    'pending':Call.all_objects.filter(status='running',created_at__gte=recent).count(),
    'inference_seconds':INFERENCE_TIMEOUT_SECONDS,'experiment':sys.argv[1],
    'calls':rows},default=str,ensure_ascii=False))
'''


def run(*args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path,data,mode=0o644,owner=(0,0)):
    fd,name=tempfile.mkstemp(prefix='.inference-fix-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        os.chmod(name,mode);os.chown(name,*owner);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def probe(current,experiment):
    result=run('systemd-run','--quiet','--wait','--pipe','--collect',
        '--unit=zhiyu-inference-'+uuid.uuid4().hex[:12],
        '-p','User=workbench','-p','Group=workbench',
        '-p','WorkingDirectory='+str(current),
        '-p','EnvironmentFile=/etc/research-workbench.env',
        str(current/'.venv/bin/python'),'-c',AUDIT_TASK,experiment,
        text=True,capture_output=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def nginx_patch(text):
    # Preserve listen/hostname/certificates/headers. Only touch the locations
    # that actually proxy to this application. Braces in comments and quoted
    # strings must not be interpreted as configuration blocks.
    tokens=re.finditer(r'''\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\$\{[^}]*\}|[{}]''',text)
    stack=[];blocks=[]
    for token in tokens:
        if token.group()=='{':stack.append(token.start())
        elif token.group()=='}':
            if not stack:raise RuntimeError('Unbalanced Nginx configuration.')
            blocks.append((stack.pop(),token.start()))
    if stack:raise RuntimeError('Unbalanced Nginx configuration.')
    changes=[];seen=set()
    for match in re.finditer(r'(?m)^[ \t]*proxy_pass\s+http://(?:127\.0\.0\.1|localhost):8000(?:/)?\s*;',text):
        parents=[b for b in blocks if b[0]<match.start()<b[1]]
        if not parents:raise RuntimeError('Cannot identify application proxy block.')
        start,end=min(parents,key=lambda b:b[1]-b[0])
        if start in seen:continue
        seen.add(start)
        inner=[b for b in blocks if start<b[0]<b[1]<end]
        directives=[m for m in re.finditer(r'(?m)^[ \t]*proxy_read_timeout\s+[^;\n]+;',text[start+1:end])
            if not any(a<start+1+m.start()<z for a,z in inner)]
        if len(directives)>1:raise RuntimeError('Duplicate proxy_read_timeout in application block.')
        if directives:
            found=directives[0];old=found.group();indent=re.match(r'[ \t]*',old).group()
            changes.append((start+1+found.start(),start+1+found.end(),indent+'proxy_read_timeout 360s;'))
        else:
            changes.append((start+1,start+1,'\n        proxy_read_timeout 360s;'))
    if not seen:raise RuntimeError('No expected application proxy found; no changes made.')
    for a,b,value in sorted(changes,reverse=True):text=text[:a]+value+text[b:]
    return text,len(seen)


def gunicorn_arguments(current):
    value=subprocess.check_output(['systemctl','show','research-workbench','-p','ExecStart','--value'],text=True)
    match=re.search(r'argv\[\]=(.*?) ;',value)
    if not match:raise RuntimeError('Cannot identify actual Gunicorn launch command.')
    args=shlex.split(match.group(1))
    if args[:2]==['/usr/bin/env','.venv/bin/gunicorn']:args=args[2:]
    elif args and args[0]==str(current/'.venv/bin/gunicorn'):args=args[1:]
    else:raise RuntimeError('Unexpected server launch command; no changes made.')
    if not args or args[0]!='config.wsgi:application':raise RuntimeError('Unexpected WSGI target.')
    clean=[];skip=False
    for arg in args:
        if skip:skip=False;continue
        if arg in ('--timeout','-t','--graceful-timeout'):skip=True;continue
        if arg.startswith(('--timeout=','--graceful-timeout=')):continue
        if '\n' in arg or '%' in arg or '$' in arg:raise RuntimeError('Unsupported launch argument.')
        clean.append(arg)
    if skip:raise RuntimeError('Incomplete Gunicorn launch option.')
    return clean+['--timeout','300','--graceful-timeout','270']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',default='EXP-A530E6481A72')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.experiment):raise SystemExit('Invalid experiment identifier.')
    if os.geteuid()!=0:raise SystemExit('Run with sudo python3.')
    if BUNDLE is None:raise SystemExit('Use the packaged standalone asset.')
    # Share the existing upgrade lock so an upgrade cannot race this patch.
    lock=open('/run/lock/research-workbench-upgrade.lock','a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('An upgrade/hotfix is already running; retry after it finishes.')
    current=Path(subprocess.check_output(['systemctl','show','research-workbench','-p','WorkingDirectory','--value'],text=True).strip())
    if current.parent!=Path('/opt/research-workbench-releases') or current.resolve()!=current or not current.is_dir():
        raise SystemExit('Cannot confirm the running release; no changes made.')
    info=json.loads((current/'desktop/release-info.json').read_text())
    if info.get('version') not in BUNDLE['versions']:raise SystemExit('Supported server versions: 0.4.2 / 0.4.4.')
    env=Path('/etc/research-workbench.env')
    if not env.is_file() or env.is_symlink():raise SystemExit('Missing production environment.')
    originals={};payload={};metadata={}
    for name,entry in BUNDLE['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='aihub':raise SystemExit('Invalid patch path.')
        target=current/relative
        if target.resolve()!=target or not target.is_file():raise SystemExit('Unexpected file: '+name)
        old=target.read_bytes();data=base64.b64decode(entry['data'],validate=True)
        if sha(old) not in entry['before']+[entry['after']]:raise SystemExit('Source differs from supported release: '+name+'. No changes made.')
        if sha(data)!=entry['after']:raise SystemExit('Invalid embedded file hash.')
        ast.parse(data,filename=name)
        originals[target]=old;payload[target]=data
    site=Path('/etc/nginx/sites-enabled/research-workbench').resolve()
    if not site.is_file() or Path('/etc/nginx') not in site.parents:raise SystemExit('Cannot confirm application Nginx site.')
    config=site.read_text()
    updated,locations=nginx_patch(config)
    # Refuse to claim all application proxy blocks were patched if another
    # active configuration also points to port 8000.
    inspected=run('nginx','-T',capture_output=True,text=True)
    selected=None
    for line in inspected.stdout.splitlines():
        marker=re.match(r'# configuration file (.*):$',line)
        if marker:selected=Path(marker.group(1)).resolve()
        if re.match(r'\s*proxy_pass\s+http://(?:127\.0\.0\.1|localhost):8000(?:/)?\s*;',line) and selected!=site:
            raise SystemExit('Another active Nginx file proxies this application; inspect it before applying.')
    dropin=Path('/etc/systemd/system/research-workbench.service.d/99-inference-timeout.conf')
    if dropin.exists() and (dropin.is_symlink() or not dropin.is_file()):raise SystemExit('Unexpected timeout drop-in.')
    if dropin.parent.is_symlink():raise SystemExit('Unexpected service drop-in directory.')
    launch=gunicorn_arguments(current)
    # Use the service WorkingDirectory, so future upgrades do not stay pinned
    # to this old release after 90-release.conf selects a new directory.
    command='/usr/bin/env .venv/bin/gunicorn '+' '.join('"'+a.replace('\\','\\\\').replace('"','\\"')+'"' for a in launch)
    originals[site]=site.read_bytes();payload[site]=updated.encode()
    originals[dropin]=dropin.read_bytes() if dropin.exists() else None
    payload[dropin]=('[Service]\nExecStart=\nExecStart='+command+'\nTimeoutStopSec=300\n').encode()
    for path,old in originals.items():
        stat=path.stat() if old is not None else None
        metadata[path]=(stat.st_mode&0o777, (stat.st_uid,stat.st_gid)) if stat else (0o644,(0,0))
    run('systemctl','is-active','--quiet','research-workbench')
    run('nginx','-t',capture_output=True)
    stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    backup=Path('/var/backups/research-workbench/inference-timeout-'+stamp)
    backup.mkdir(mode=0o700,parents=True)
    for path,old in originals.items():
        if old is not None:
            relative=path.relative_to(current) if current in path.parents else Path('configuration')/path.name
            saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(old)
    manifest={'release':str(current),'source_commit':BUNDLE['source_commit'],
        'files':{str(p):{'existed':v is not None,'sha256':sha(v) if v else None} for p,v in originals.items()}}
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    replaced=[];restart_requested=False;nginx_reloaded=False
    try:
        dropin.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        # The audit helper imports the new inference constant. Install code
        # before its isolated read-only process; existing workers keep old code
        # until the controlled restart below.
        for path,data in payload.items():
            if data!=originals[path]:
                mode,owner=metadata[path];write(path,data,mode,owner);replaced.append(path)
        run('nginx','-t',capture_output=True)
        audit=probe(current,args.experiment)
        if audit['database_engine']!='django.db.backends.sqlite3' or Path(audit['database']).resolve()!=Path('/var/lib/research-workbench/workbench.sqlite3'):
            raise RuntimeError('Unexpected production database; no database writes were made.')
        (backup/'billing-review.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
        for waiting in range(16):
            if not audit['pending']:break
            if waiting==15:raise RuntimeError('Recent inference still running; patch deferred to avoid interrupting billed requests.')
            print('Waiting for '+str(audit['pending'])+' existing inference request(s)...',flush=True)
            time.sleep(5);audit=probe(current,args.experiment)
        run('systemctl','daemon-reload')
        restart_requested=True
        run('systemctl','restart','research-workbench')
        healthy=False
        for attempt in range(15):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/healthz/',timeout=4) as response:
                    healthy=json.load(response).get('status')=='ok'
                if healthy:break
            except Exception:pass
            time.sleep(1)
        if not healthy:raise RuntimeError('Application did not recover after restart.')
        run('systemctl','reload','nginx')
        nginx_reloaded=True
        actual=subprocess.check_output(['systemctl','show','research-workbench','-p','ExecStart','--value'],text=True)
        if '--timeout 300' not in actual or '--graceful-timeout 270' not in actual:
            raise RuntimeError('Gunicorn did not load the expected timeout.')
        after=probe(current,args.experiment)
        if after['inference_seconds']!=240:raise RuntimeError('Inference timeout was not loaded.')
        unknown=sum(1 for row in after['calls'] if row['status']=='unknown' and not row['reconciled'])
        (backup/'billing-review.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
        print('HOTFIX OK: inference=240s; Gunicorn=300s; Nginx=360s ('+str(locations)+' proxy locations).',flush=True)
        print('Billing audit: '+str(len(after['calls']))+' calls for '+args.experiment+'; '+str(unknown)+' awaiting reconciliation. No billing records changed.',flush=True)
        print('Backup and billing-review.json: '+str(backup),flush=True)
    except Exception:
        for path in reversed(replaced):
            old=originals[path]
            if old is None:path.unlink()
            else:
                mode,owner=metadata[path];write(path,old,mode,owner)
        subprocess.run(['systemctl','daemon-reload'],check=False)
        subprocess.run(['nginx','-t'],check=False)
        if restart_requested:subprocess.run(['systemctl','restart','research-workbench'],check=False)
        if nginx_reloaded:subprocess.run(['systemctl','reload','nginx'],check=False)
        print('Hotfix failed/deferred; original code and configuration restored. Backup: '+str(backup),flush=True)
        raise


if __name__=='__main__':main()
