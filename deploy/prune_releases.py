"""Prune timestamped code releases, never application data or backups.

Default: print a plan. --apply: execute it under the upgrade lock.
Requires Linux/root/systemd. No environment values or credentials are printed.
"""
import argparse
import fcntl
import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path('/opt/research-workbench-releases')
BACKUPS = Path('/var/backups/research-workbench')
LOCK = Path('/run/lock/research-workbench-upgrade.lock')
NAME = re.compile(r'\d{8}-\d{6}')
REFERENCE = re.compile(re.escape(str(ROOT)) + r'/(\d{8}-\d{6})(?=$|[/\s\x00"\'=:;])')


def command(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8', errors='replace', timeout=30)


def references(text):
    return {ROOT / match for match in REFERENCE.findall(text)}


def runtime_references():
    # Inspect configured as well as loaded units: a stopped scheduled worker
    # may still need an older runtime on its next invocation.
    units = set()
    for operation in ('list-unit-files', 'list-units'):
        output = command('systemctl', operation, '--all', '--type=service', '--no-legend', '--plain')
        units.update(line.split()[0] for line in output.splitlines() if line.split())
    if not units:
        raise RuntimeError('无法取得服务配置，停止清理。')
    protected = references(command(
        'systemctl', 'show', '--property=WorkingDirectory,ExecStart,Environment,EnvironmentFiles,RootDirectory,ReadWritePaths',
        *sorted(units),
    ))
    # Configured services alone do not cover manual/old worker processes.
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            for item in ('cwd', 'exe'):
                try:
                    protected.update(references(os.readlink(process / item)))
                except FileNotFoundError:
                    pass  # Kernel threads or processes that have exited.
            for item in ('cmdline', 'environ'):
                protected.update(references((process / item).read_bytes().decode('utf-8', errors='replace')))
        except (FileNotFoundError, ProcessLookupError):
            pass
        # Permission and other unexpected failures intentionally stop cleanup.
    return protected


def rollback_references():
    if not BACKUPS.exists():
        return set()
    # Keep the actual previous service configuration from the most recent full
    # backup, rather than guessing that a preparation-only release was live.
    for backup in sorted(BACKUPS.glob('upgrade-*'), reverse=True):
        if backup.is_symlink() or not backup.is_dir():
            continue
        if all((backup / name).is_file() for name in
               ('data-and-keys.tar.gz', 'workbench.sqlite3', 'environment.env', 'service-before.txt')):
            return references((backup / 'service-before.txt').read_text(encoding='utf-8', errors='replace'))
    return set()


def data_or_mount_present(release):
    # Only normal deployment output is disposable. Unexpected databases,
    # credential stores and mounted directories require a separate audit.
    for parent, directories, files in os.walk(release, followlinks=False):
        base = Path(parent)
        if any(os.path.ismount(base / name) for name in directories):
            return True
        for name in files:
            path = base / name
            if (name == 'api-pool-keys.json' or name in ('.env', 'environment.env', 'research-workbench.env')
                    or (name == 'workbench.sqlite3' and path.parent != release / '.upgrade-check-data')):
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--protect', action='append', default=[])
    parser.add_argument('--upgrade-lock-held', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('请用 sudo python3 运行，才能核对所有服务和进程。')
    if ROOT.is_symlink() or ROOT.resolve() != ROOT or not ROOT.is_dir():
        parser.error('版本根目录无效，停止清理。')
    if not shutil.rmtree.avoids_symlink_attacks:
        parser.error('当前 Python 不支持安全的目录删除，停止清理。')
    with LOCK.open('a') as lock:
        if args.upgrade_lock_held:
            inherited = os.fstat(9)
            expected = os.fstat(lock.fileno())
            if (inherited.st_dev, inherited.st_ino) != (expected.st_dev, expected.st_ino):
                parser.error('没有继承升级锁，停止清理。')
            fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error('升级正在运行，请等待完成。')
        current = Path(command('systemctl', 'show', 'research-workbench', '-p', 'WorkingDirectory', '--value').strip())
        if (current.parent != ROOT or not NAME.fullmatch(current.name) or not current.is_dir()
                or current.is_symlink() or current.resolve() != current):
            parser.error('无法确认正在使用的版本目录，停止清理。')
        releases = sorted((path for path in ROOT.iterdir()
                           if NAME.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
                           and path.resolve() == path and not os.path.ismount(path)), reverse=True)
        protected = runtime_references() | rollback_references() | {current}
        for argument in args.protect:
            if argument:
                protected.update(references(str(Path(argument).resolve())))
        older = [path for path in releases if path.name < current.name]
        if older:
            protected.add(older[0])  # One recent release for rollback.
        # Newer directories may be a pending upgrade; do not erase them.
        protected.update(path for path in releases if path.name > current.name)
        removed = 0
        for release in releases:
            if release in protected or data_or_mount_present(release):
                print('保留：' + str(release), flush=True)
                continue
            if not (release / 'manage.py').is_file() or not (release / '.venv').is_dir():
                print('跳过未知目录：' + str(release), flush=True)
                continue
            print(('清理：' if args.apply else '计划清理：') + str(release), flush=True)
            if args.apply:
                # Recheck immediately before each removal, including containment
                # and live references; never follow a replaced symlink.
                if (release.is_symlink() or release.resolve() != release or release.parent != ROOT
                        or release in runtime_references() or data_or_mount_present(release)):
                    raise RuntimeError('目录状态发生变化，停止清理：' + str(release))
                shutil.rmtree(release)
                removed += 1
        print(f'已清理 {removed} 个旧版本。' if args.apply else '以上仅为计划，没有删除文件。', flush=True)


if __name__ == '__main__':
    main()
