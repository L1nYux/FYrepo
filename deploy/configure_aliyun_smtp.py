#!/usr/bin/env python3
"""Configure the existing production service without touching application data."""

import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import smtplib
import ssl
import stat
import subprocess
import tempfile
import time
import urllib.request
import warnings


ENV_FILE = Path('/etc/research-workbench.env')
SERVICE = 'research-workbench'
HOST = 'smtp.qiye.aliyun.com'
PORT = 465
MAIL_KEYS = {
    'WORKBENCH_EMAIL_HOST', 'WORKBENCH_EMAIL_PORT', 'WORKBENCH_EMAIL_USER',
    'WORKBENCH_EMAIL_PASSWORD', 'WORKBENCH_EMAIL_TLS', 'WORKBENCH_EMAIL_SSL',
    'WORKBENCH_EMAIL_FROM',
}


def run(*args, timeout=30):
    return subprocess.run(args, capture_output=True, timeout=timeout, check=False)


def env_quote(value):
    # These double-quote escapes are understood by both bash (upgrade script)
    # and systemd EnvironmentFile. Neither may expand password characters.
    if any(c in value for c in '\r\n\x00'):
        raise ValueError('邮箱参数不能包含换行或空字符。')
    for character in ('\\', '"', '$', '`'):
        value = value.replace(character, '\\' + character)
    return '"' + value + '"'


def configure_text(original, values):
    kept = []
    for line in original.splitlines(keepends=True):
        assignment = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line.rstrip('\r\n'))
        if assignment and assignment.group(1) in MAIL_KEYS:
            # Do not leave fragments of an existing multiline assignment.
            shlex.split(assignment.group(2), comments=True)
            if assignment.group(2).endswith('\\'):
                raise ValueError('已有邮件参数包含跨行内容，请先整理成单行。')
            continue
        kept.append(line)
    text = ''.join(kept)
    if text and not text.endswith('\n'):
        text += '\n'
    return text + ''.join(key + '=' + env_quote(value) + '\n' for key, value in values.items())


def atomic_write(path, data, metadata):
    descriptor, temporary = tempfile.mkstemp(prefix='.workbench-mail-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(metadata.st_mode) & 0o640)
            os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def status_host():
    # Read only the allowed-hosts value; never display the environment file.
    result = run('bash', '-c', 'source "$1" >/dev/null 2>&1 && printf "%s" "${WORKBENCH_ALLOWED_HOSTS-}"',
                 'workbench-mail', str(ENV_FILE))
    if result.returncode:
        raise ValueError('现有环境配置无法读取，请先检查其格式。')
    allowed = result.stdout.decode('utf-8').split(',')
    return next((v.strip() for v in allowed if v.strip() and v.strip() != '*' and not v.strip().startswith('.')),
                '127.0.0.1')


def service_ready(host):
    # Use localhost directly, independent of machine proxy configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request('http://127.0.0.1:8000/desktop/api/status/', headers={'Host': host})
    for _ in range(10):
        try:
            if run('systemctl', 'is-active', '--quiet', SERVICE, timeout=5).returncode == 0:
                with opener.open(request, timeout=2) as response:
                    value = json.load(response)
                if value.get('protocol') == 1:
                    return True
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser(description='保存阿里邮箱 SMTP 配置并重启现有工作台。')
    parser.add_argument('--user', required=True, help='完整邮箱地址；密码在终端隐藏输入')
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('请通过 sudo 或 root 执行。')
    user = arguments.user.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', user):
        raise ValueError('请填写完整邮箱地址。')
    metadata = ENV_FILE.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError('现有环境配置必须是 root 所有且不能被其他用户写入的普通文件。')
    environment_files = run('systemctl', 'show', SERVICE, '--property=EnvironmentFiles', '--value')
    if environment_files.returncode or str(ENV_FILE) not in environment_files.stdout.decode('utf-8'):
        raise ValueError('工作台服务没有使用预期的环境文件，请先确认部署配置。')
    original = ENV_FILE.read_bytes()
    host = status_host()
    warnings.simplefilter('error', getpass.GetPassWarning)
    print('邮箱：' + user)
    print('等下面出现 Mailbox password 后输入邮箱密码并回车；输入不会显示。', flush=True)
    password = getpass.getpass('Mailbox password: ')
    if not password:
        raise ValueError('密码为空，配置未修改。')
    values = {
        'WORKBENCH_EMAIL_HOST': HOST, 'WORKBENCH_EMAIL_PORT': str(PORT),
        'WORKBENCH_EMAIL_USER': user, 'WORKBENCH_EMAIL_PASSWORD': password,
        'WORKBENCH_EMAIL_TLS': '0', 'WORKBENCH_EMAIL_SSL': '1',
        'WORKBENCH_EMAIL_FROM': user,
    }
    updated = configure_text(original.decode('utf-8'), values).encode('utf-8')
    print('正在验证邮箱登录……', flush=True)
    with smtplib.SMTP_SSL(HOST, PORT, timeout=20, context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
    backup_root = Path('/var/backups/research-workbench')
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_directory = Path(tempfile.mkdtemp(prefix='smtp-' + stamp + '-', dir=backup_root))
    backup = backup_directory / 'environment.env'
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(original)
        output.flush()
        os.fsync(output.fileno())
    if ENV_FILE.read_bytes() != original:
        raise ValueError('配置已被其他操作修改，停止保存；请重新执行。')
    changed = False
    try:
        # Mark before replacement so even an interruption immediately after
        # os.replace will restore the original file.
        changed = True
        atomic_write(ENV_FILE, updated, metadata)
        print('邮件配置已保存，正在重启工作台……', flush=True)
        if run('systemctl', 'restart', SERVICE, timeout=60).returncode or not service_ready(host):
            raise RuntimeError('工作台启动检查未通过。')
    except BaseException:
        if changed:
            atomic_write(ENV_FILE, original, metadata)
            try:
                run('systemctl', 'restart', SERVICE, timeout=60)
                restored = service_ready(host)
            except (OSError, subprocess.TimeoutExpired):
                restored = False
            print('已恢复原邮件配置；工作台' + ('已恢复运行。' if restored else '仍需检查启动状态。'))
            print('配置备份：' + str(backup))
        raise
    print('SMTP 配置完成，工作台运行正常。')
    print('发件邮箱：' + user)
    print('配置备份：' + str(backup))
    print('可在登录页使用“忘记密码”，确认实际邮件能收到。')


if __name__ == '__main__':
    try:
        main()
    except smtplib.SMTPAuthenticationError as error:
        print('邮箱认证失败（SMTP ' + str(error.smtp_code) + '），没有保存新配置。')
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError, getpass.GetPassWarning):
        print('输入已取消或终端无法隐藏密码，请在交互终端重新执行。')
        raise SystemExit(1)
    except Exception as error:
        # No raw traceback or server response: never echo credentials.
        if isinstance(error, (ValueError, RuntimeError)):
            print(str(error))
        else:
            print('配置未完成（' + type(error).__name__ + '），请检查终端连接和服务器状态。')
        raise SystemExit(1)
