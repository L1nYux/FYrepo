"""Prepare/apply the additive phone-history patch to the running 0.4.4 release.

The distributable embeds public application files in BUNDLE. It preserves the
live database, credentials, API keys, inference hotfix and network configuration.
"""
import argparse
import ast
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import uuid

BUNDLE = None  # Embedded only when packaging the standalone installer.
FILES = {'core/models.py', 'core/apps.py', 'core/urls.py',
         'core/local_chat_delivery.py', 'core/migrations/0047_local_chat_delivery.py',
         'core/management/commands/prune_delivered_chat.py'}
SERVICE = Path('/etc/systemd/system/research-workbench-chat-cleanup.service')
TIMER = Path('/etc/systemd/system/research-workbench-chat-cleanup.timer')

PROBE = """
import os,json
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.utils import timezone
from aihub.models import Call
d=settings.DATABASES['default']
print(json.dumps({'database':str(d['NAME']),'engine':d['ENGINE'],
 'running':Call.all_objects.filter(status='running',created_at__gte=timezone.now()-timezone.timedelta(minutes=10)).count()}))
"""


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def service_task(current, *command):
    return run('systemd-run', '--quiet', '--wait', '--pipe', '--collect',
        '--unit=zhiyu-chat-setup-' + uuid.uuid4().hex[:12],
        '-p', 'User=workbench', '-p', 'Group=workbench',
        '-p', 'WorkingDirectory=' + str(current),
        '-p', 'EnvironmentFile=/etc/research-workbench.env',
        str(current / '.venv/bin/python'), *command, text=True, capture_output=True)


def write(path, data, mode, owner):
    fd, name = tempfile.mkstemp(prefix='.chat-patch-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        os.chmod(name, mode); os.chown(name, *owner); os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    if os.geteuid() != 0: raise SystemExit('请使用 sudo python3 运行。')
    if not BUNDLE or set(BUNDLE['files']) != FILES: raise SystemExit('需要已打包的独立补丁。')
    lock = open('/run/lock/research-workbench-upgrade.lock', 'a')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('升级或热修正在进行，请稍后重试。')
    current = Path(subprocess.check_output(['systemctl', 'show', 'research-workbench', '-p', 'WorkingDirectory', '--value'], text=True).strip())
    if current.parent != Path('/opt/research-workbench-releases') or current.resolve() != current or not current.is_dir():
        raise SystemExit('无法确认当前运行目录，没有改动。')
    info = json.loads((current / 'desktop/release-info.json').read_text())
    if info.get('version') != '0.4.4': raise SystemExit('仅支持当前 0.4.4 服务器，没有改动。')
    payload, original, metadata = {}, {}, {}
    for relative, entry in BUNDLE['files'].items():
        path = current / relative
        if path.resolve() != path or not path.parent.is_dir() or path.exists() and not path.is_file():
            raise SystemExit('文件路径异常：' + relative)
        old = path.read_bytes() if path.exists() else None
        if old is not None and digest(old.replace(b'\r\n', b'\n')) not in entry['before'] + [entry['after']]:
            raise SystemExit('服务器源码与预期不一致：' + relative + '，没有改动。')
        if old is None and entry['before']: raise SystemExit('缺少原有文件：' + relative)
        data = base64.b64decode(entry['data'], validate=True)
        if digest(data) != entry['after']: raise SystemExit('补丁校验失败。')
        ast.parse(data, filename=relative)
        stat = path.stat() if old is not None else path.parent.stat()
        metadata[path] = (stat.st_mode & 0o777 if old is not None else 0o644, (stat.st_uid, stat.st_gid))
        original[path], payload[path] = old, data
    for path in (SERVICE, TIMER):
        if path.is_symlink() or path.exists() and not path.is_file(): raise SystemExit('清理服务路径异常。')
        original[path] = path.read_bytes() if path.exists() else None
        stat = path.stat() if path.exists() else None
        metadata[path] = (stat.st_mode & 0o777, (stat.st_uid, stat.st_gid)) if stat else (0o644, (0, 0))
    payload[SERVICE] = b'''[Unit]
Description=Clean up acknowledged ordinary chat after 30 days
After=research-workbench.service
[Service]
Type=oneshot
User=workbench
Group=workbench
EnvironmentFile=/etc/research-workbench.env
ExecStart=/bin/bash -eu -c 'current=$(/bin/systemctl show research-workbench -p WorkingDirectory --value); case "$current" in /opt/research-workbench-releases/*) ;; *) exit 2 ;; esac; cd "$current"; exec .venv/bin/python manage.py prune_delivered_chat --apply --limit 5000'
Nice=10
'''
    payload[TIMER] = b'''[Unit]
Description=Daily delivered chat cleanup
[Timer]
OnCalendar=*-*-* 03:40:00
RandomizedDelaySec=300
Persistent=true
[Install]
WantedBy=timers.target
'''
    probe = json.loads(service_task(current, '-c', PROBE).stdout.strip().splitlines()[-1])
    database = Path(probe['database'])
    if probe['engine'] != 'django.db.backends.sqlite3' or database.resolve() != Path('/var/lib/research-workbench/workbench.sqlite3'):
        raise SystemExit('数据库位置异常，没有改动。')
    if not options.apply:
        print('准备完成：保留现有数据库和 API；新增本机收取确认与 30 天后台清理。使用 --apply 正式安装。')
        return
    if probe['running']: raise SystemExit('仍有 AI 请求运行，请结束后重试，避免中断计费请求。')
    backup = Path('/var/backups/research-workbench/chat-history-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    backup.mkdir(mode=0o700, parents=True)
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True) as source, sqlite3.connect(backup / 'workbench.sqlite3') as target:
        source.backup(target)
    for path, data in original.items():
        if data is not None:
            relative = path.relative_to(current) if current in path.parents else Path('systemd') / path.name
            saved = backup / relative; saved.parent.mkdir(parents=True, exist_ok=True); saved.write_bytes(data)
    (backup / 'manifest.json').write_text(json.dumps({'release':str(current), 'source_commit':BUNDLE['source_commit'], 'files':{str(path):data is not None for path,data in original.items()}}, indent=2))
    changed = []
    timer_was_enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet', TIMER.name]).returncode == 0
    timer_was_active = subprocess.run(['systemctl', 'is-active', '--quiet', TIMER.name]).returncode == 0
    run('systemctl', 'stop', 'research-workbench')
    try:
        for path, data in payload.items():
            if data != original[path]:
                write(path, data, *metadata[path]); changed.append(path)
        service_task(current, 'manage.py', 'migrate', 'core', '--noinput')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'research-workbench')
        run('systemctl', 'is-active', '--quiet', 'research-workbench')
        run('systemctl', 'enable', '--now', TIMER.name)
        print('安装完成。客户端保存成功并全部收取 30 天后才清理普通文字消息；旧记录、附件和积分等保留。')
        print('备份：' + str(backup))
    except Exception:
        subprocess.run(['systemctl', 'stop', 'research-workbench', TIMER.name], check=False)
        for path in reversed(changed):
            if original[path] is None: path.unlink()
            else: write(path, original[path], *metadata[path])
        subprocess.run(['systemctl', 'daemon-reload'], check=False)
        if not timer_was_enabled: subprocess.run(['systemctl', 'disable', TIMER.name], check=False)
        if timer_was_active: subprocess.run(['systemctl', 'start', TIMER.name], check=False)
        subprocess.run(['systemctl', 'start', 'research-workbench'], check=False)
        print('补丁失败，已还原代码。新建空表可能保留；没有还原覆盖业务数据库。备份：' + str(backup))
        raise


if __name__ == '__main__': main()
