"""Recover the previous running release after an accidental 0.4.0 upgrade.

The upgrade's own configuration backup identifies the recovery target. The
live database and environment are preserved, with a fresh backup made first.
Packaging embeds the separately verified inference timeout installer.
"""
import base64
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import uuid

TIMEOUT_PATCH = None  # Embedded only in the standalone recovery asset.

PROBE = r'''
import json,os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone
from aihub.models import Call
loader=MigrationLoader(connection,ignore_no_migrations=True)
unknown=sorted([list(m) for m in loader.applied_migrations
    if m[0] in ('core','aihub','sampling') and m not in loader.disk_migrations])
db=settings.DATABASES['default']
print(json.dumps({'database':str(db['NAME']),'engine':db['ENGINE'],
    'unknown_migrations':unknown,'pending':Call.all_objects.filter(status='running',
    created_at__gte=timezone.now()-timezone.timedelta(minutes=5)).count()}))
'''


def run(*args,**kwargs):return subprocess.run(args,check=True,**kwargs)


def active(unit):return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0


def atomic_write(path,data,mode=0o644,owner=(0,0)):
    path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.recovery-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        os.chmod(tmp,mode);os.chown(tmp,*owner);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def service_probe(target):
    result=run('systemd-run','--quiet','--wait','--pipe','--collect',
        '--unit=zhiyu-recovery-'+uuid.uuid4().hex[:12],
        '-p','User=workbench','-p','Group=workbench',
        '-p','WorkingDirectory='+str(target),
        '-p','EnvironmentFile=/etc/research-workbench.env',
        str(target/'.venv/bin/python'),'-c',PROBE,text=True,capture_output=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def confirmed_release(path):
    if path.parent!=Path('/opt/research-workbench-releases') or path.resolve()!=path or not path.is_dir():
        raise SystemExit('Cannot confirm release directory; no changes made.')
    if not (path/'manage.py').is_file() or not os.access(path/'.venv/bin/python',os.X_OK):
        raise SystemExit('Previous code/runtime missing; no changes made.')
    return json.loads((path/'desktop/release-info.json').read_text())['version']


def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo python3.')
    if TIMEOUT_PATCH is None:raise SystemExit('Use the packaged recovery asset.')
    code=gzip.decompress(base64.b64decode(TIMEOUT_PATCH['data'],validate=True))
    if hashlib.sha256(code).hexdigest()!=TIMEOUT_PATCH['sha256']:raise SystemExit('Embedded patch hash mismatch.')
    lock=open('/run/lock/research-workbench-upgrade.lock','a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('An upgrade is running; wait until it finishes.')
    current=Path(subprocess.check_output(['systemctl','show','research-workbench','-p','WorkingDirectory','--value'],text=True).strip())
    version=confirmed_release(current)
    if version not in ('0.4.0','0.4.1'):
        raise SystemExit('Current server is '+version+'. Recovery is only for accidental 0.4.0 / 0.4.1 installs; no changes made.')
    prior_backup=Path('/var/backups/research-workbench')/('upgrade-'+current.name)
    if prior_backup.resolve()!=prior_backup or not prior_backup.is_dir():raise SystemExit('Cannot confirm this upgrade backup.')
    before=prior_backup/'service-before.txt'
    release_override=prior_backup/'90-release.conf'
    if not before.is_file() or not release_override.is_file():raise SystemExit('Original service configuration missing; no changes made.')
    values=re.findall(r'(?m)^WorkingDirectory=(/[^\r\n]+)',before.read_text())
    if not values:raise SystemExit('Original running directory is absent from backup.')
    target=Path(values[-1]);target_version=confirmed_release(target)
    if target==current or target_version not in ('0.4.2','0.4.4'):
        raise SystemExit('Previous release is not a confirmed 0.4.2 / 0.4.4; no changes made.')
    override=release_override.read_bytes()
    recovered_values=re.findall(r'(?m)^WorkingDirectory=(/[^\r\n]+)',override.decode())
    if not recovered_values or Path(recovered_values[-1])!=target:
        raise SystemExit('Previous service backup disagrees with original running directory.')
    env=Path('/etc/research-workbench.env')
    if env.is_symlink() or not env.is_file():raise SystemExit('Cannot confirm the production environment.')
    probe=service_probe(target)
    if probe['engine']!='django.db.backends.sqlite3' or Path(probe['database']).resolve()!=Path('/var/lib/research-workbench/workbench.sqlite3'):
        raise SystemExit('Unexpected live database; no changes made.')
    if probe['unknown_migrations']:raise SystemExit('Previous code cannot describe all database migrations; no changes made.')
    # Let old requests settle before stopping services. No inference is resent.
    for attempt in range(16):
        if not probe['pending']:break
        if attempt==15:raise SystemExit('Inference is still running. Recovery deferred; no changes made.')
        print('Waiting for '+str(probe['pending'])+' active inference request(s)...',flush=True)
        time.sleep(5);probe=service_probe(target)
    dropin=Path('/etc/systemd/system/research-workbench.service.d/90-release.conf')
    payload={dropin:override}
    units={
        'research-workbench-prices.service':'prices.service',
        'research-workbench-gifts.service':'gifts.service',
        'research-workbench-releases.service':'releases.service',
        'research-sampling-worker.service':'sampling.service',
        'research-workbench-prices.timer':'prices.timer',
        'research-workbench-gifts.timer':'gifts.timer',
        'research-workbench-releases.timer':'releases.timer',
    }
    for unit,saved_name in units.items():
        path=Path('/etc/systemd/system')/unit;saved=prior_backup/saved_name
        if saved.is_file():payload[path]=saved.read_bytes()
        elif path.is_file():
            data=path.read_bytes()
            # Older upgrade scripts may not back up every helper unit. Redirect
            # only the accidental release path; retain all other unit settings.
            updated=data.replace(str(current).encode(),str(target).encode())
            if updated!=data:payload[path]=updated
    original={};metadata={}
    for path in payload:
        if path.is_symlink() or path.parent.is_symlink():raise SystemExit('Unexpected service configuration link.')
        original[path]=path.read_bytes() if path.exists() else None
        stat=path.stat() if path.exists() else None
        metadata[path]=(stat.st_mode&0o777,(stat.st_uid,stat.st_gid)) if stat else (0o644,(0,0))
    stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    backup=Path('/var/backups/research-workbench/recovery-'+stamp);backup.mkdir(mode=0o700,parents=True)
    for path,data in original.items():
        if data is not None:(backup/path.name).write_bytes(data)
    (backup/'environment.env').write_bytes(env.read_bytes())
    (backup/'manifest.json').write_text(json.dumps({'from':str(current),'to':str(target),
        'version':target_version,'prior_upgrade_backup':str(prior_backup),'probe':probe},indent=2))
    order=['research-workbench-prices.timer','research-workbench-gifts.timer','research-workbench-releases.timer',
        'research-workbench-prices.service','research-workbench-gifts.service','research-workbench-releases.service',
        'research-sampling-worker.service','research-workbench.service']
    running=[unit for unit in order if active(unit)];stopped=[];replaced=[]
    try:
        for unit in running:run('systemctl','stop',unit);stopped.append(unit)
        database=Path(probe['database'])
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as source,sqlite3.connect(str(backup/'workbench.sqlite3')) as destination:
            source.backup(destination)
        os.chmod(backup/'workbench.sqlite3',0o600)
        for path,data in payload.items():
            if data!=original[path]:
                mode,owner=metadata[path];atomic_write(path,data,mode,owner);replaced.append(path)
        run('systemctl','daemon-reload');run('systemctl','start','research-workbench.service')
        healthy=False
        for attempt in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/healthz/',timeout=4) as response:
                    healthy=json.load(response).get('status')=='ok'
                if healthy:break
            except Exception:pass
            time.sleep(1)
        if not healthy:raise RuntimeError('Recovered application is not healthy.')
        actual=Path(subprocess.check_output(['systemctl','show','research-workbench','-p','WorkingDirectory','--value'],text=True).strip())
        if actual!=target:raise RuntimeError('Service did not select the previous release.')
        with urllib.request.urlopen('http://127.0.0.1:8000/desktop/api/status/',timeout=10) as response:
            status=json.load(response)
        if status.get('serverVersion')!=target_version:
            raise RuntimeError('Running API version disagrees with the recovered release.')
        # Match helper unit directories with the confirmed previous code.
        for unit in units:
            if unit.endswith('.service') and (Path('/etc/systemd/system')/unit).exists():
                directory=subprocess.check_output(['systemctl','show',unit,'-p','WorkingDirectory','--value'],text=True,stderr=subprocess.DEVNULL).strip()
                if directory==str(current):raise RuntimeError('A background service still targets the accidental release.')
        print('RECOVERY OK: server '+version+' -> '+target_version,flush=True)
        print('Running release: '+str(target),flush=True)
        print('Live database and API keys preserved. Backup: '+str(backup),flush=True)
    except Exception:
        subprocess.run(['systemctl','stop','research-workbench.service'],check=False)
        for path in reversed(replaced):
            if original[path] is None:path.unlink()
            else:
                mode,owner=metadata[path];atomic_write(path,original[path],mode,owner)
        subprocess.run(['systemctl','daemon-reload'],check=False)
        print('Recovery failed; service configuration restored. Live database was not replaced. Backup: '+str(backup),flush=True)
        raise
    finally:
        for unit in reversed(stopped):subprocess.run(['systemctl','start',unit],check=False)
    # Separate failure boundary: if timeout patch cannot apply, keep the now
    # recovered previous version; never return to the accidental downgrade.
    lock.close()
    fd,patch=tempfile.mkstemp(prefix='zhiyu-recovered-timeout-',suffix='.py')
    try:
        with os.fdopen(fd,'wb') as out:out.write(code)
        result=subprocess.run(['/usr/bin/python3',patch])
        if result.returncode:
            raise SystemExit('Previous version recovered, but timeout patch did not complete. Send this output for follow-up.')
    finally:
        os.unlink(patch)
    print('RECOVERY AND TIMEOUT HOTFIX COMPLETE.',flush=True)


if __name__=='__main__':main()
