"""Reconstruct a source tree from a matching installed release, then upgrade normally.

The bundle contains changed source files and exact before/after hashes only.
It never patches the running directory, the database, configuration or API keys.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run this command with sudo.')
    bundle = Path(__file__).resolve().parent
    manifest = json.loads((bundle / 'HOTFIX-MANIFEST.json').read_text(encoding='utf-8'))
    current = Path(subprocess.check_output(['systemctl', 'show', 'research-workbench',
        '-p', 'WorkingDirectory', '--value'], text=True).strip())
    root = Path('/opt/research-workbench-releases')
    if current.parent != root or current.is_symlink() or current.resolve() != current or not current.is_dir():
        raise SystemExit('Cannot confirm the running release directory.')
    installed = json.loads((current / 'desktop/release-info.json').read_text(encoding='utf-8'))
    if installed['version'] != manifest['from_version']:
        raise SystemExit('This hotfix requires server version ' + manifest['from_version'])
    if digest(current / 'deploy/upgrade_preserve_data.sh') != manifest['upgrade_script_sha256']:
        raise SystemExit('Upgrade script differs from the expected release; no changes made.')
    allowed = {'config', 'core', 'aihub', 'sampling', 'vendor', 'tools', 'templates', 'static', 'deploy'}
    for name, entry in manifest['files'].items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or not relative.parts
                or relative.parts[0] not in allowed and name != 'desktop/release-info.json'):
            raise SystemExit('Invalid source path: ' + name)
        source = bundle / 'files' / name
        if source.is_symlink() or not source.is_file() or digest(source) != entry['after']:
            raise SystemExit('Hotfix file integrity check failed: ' + name)
        previous = current / name
        if previous.is_symlink() or (entry['before'] is None and previous.exists()):
            raise SystemExit('Unexpected existing source: ' + name)
        if entry['before'] is not None and (not previous.is_file() or digest(previous) != entry['before']):
            raise SystemExit('Installed source differs; no changes made: ' + name)
    # All checks above happen before making a source copy or invoking the upgrader.
    staged = Path(tempfile.mkdtemp(prefix='zhiyu-hotfix-' + manifest['to_version'] + '-', dir='/tmp'))
    staged.chmod(0o755)
    for name in sorted(allowed | {'manage.py', 'requirements.txt'}):
        source = current / name
        if source.is_symlink():
            raise SystemExit('Unexpected source symlink: ' + name)
        if source.is_dir():
            shutil.copytree(source, staged / name, symlinks=True, ignore=shutil.ignore_patterns('__pycache__'))
        elif source.is_file():
            shutil.copy2(source, staged / name)
    (staged / 'desktop').mkdir()
    shutil.copy2(current / 'desktop/release-info.json', staged / 'desktop/release-info.json')
    for name in manifest['files']:
        target = staged / name
        if not target.resolve().is_relative_to(staged):
            raise SystemExit('Source path escapes the staged directory: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / 'files' / name, target)
    print('Verified source prepared: ' + str(staged), flush=True)
    subprocess.run(['bash', str(staged / 'deploy/upgrade_preserve_data.sh'), '--apply'], check=True)


if __name__ == '__main__':
    main()
