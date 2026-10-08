"""Archive the current source snapshot, including uncommitted fixes, without data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.test-scratch',
             '.local', 'private_uploads', 'media', 'uploads', 'backups', 'staticfiles'}


def prepare(output):
    version = json.loads((ROOT/'desktop/package.json').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid source version')
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others',
                                     '--exclude-standard', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    prefix = 'zhiyu-' + version + '/'
    manifest = {'version': version, 'snapshot': 'unpublished-working-tree',
                'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                'prepared_at': datetime.now(timezone.utc).isoformat(), 'files': {}}
    output = output.resolve()
    if output.exists():
        raise ValueError('Choose a new archive path; an existing archive is not overwritten')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(set(names) - {''}):
            relative = PurePosixPath(name)
            file = ROOT.joinpath(*relative.parts)
            if relative.is_absolute() or '..' in relative.parts or file.is_symlink():
                raise ValueError('Unsafe source path: ' + name)
            if not file.is_file():
                continue  # A locally deleted tracked source stays deleted in the snapshot.
            if not file.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Source path escapes repository: ' + name)
            if FORBIDDEN.intersection(relative.parts) or relative.parts[:2] == ('desktop', 'dist'):
                raise ValueError('Runtime directory included: ' + name)
            lower = relative.name.lower()
            if (lower.startswith('.env') and lower != '.env.example' or lower == 'api-pool-keys.json'
                    or lower.endswith(('.sqlite3', '.db', '.log', '.pem', '.key'))):
                raise ValueError('Private data/configuration included: ' + name)
            data = file.read_bytes()
            # Zip extraction on Linux does not translate Windows shell line endings.
            if relative.suffix == '.sh':
                data = data.replace(b'\r\n', b'\n')
            manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            info = zipfile.ZipInfo(prefix + name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if relative.suffix == '.sh' else 0o100644) << 16
            archive.writestr(info, data)
        archive.writestr(prefix+'SOURCE-MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise ValueError('Archive integrity failure')
        for name, entry in manifest['files'].items():
            if hashlib.sha256(archive.read(prefix+name)).hexdigest() != entry['sha256']:
                raise ValueError('Source hash mismatch: ' + name)
        for required in ('manage.py', 'requirements.txt', 'desktop/release-info.json',
                         'deploy/upgrade_preserve_data.sh', 'sampling/migrations/0004_workspace_ownership.py',
                         'core/migrations/0045_clarify_api_reimbursement.py', 'static/core/emoji.js',
                         'static/core/comment-emoji.js', 'static/vendor/emoji-mart/data.json'):
            archive.getinfo(prefix+required)
    print(json.dumps({'archive': str(output), 'files': len(manifest['files']),
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
