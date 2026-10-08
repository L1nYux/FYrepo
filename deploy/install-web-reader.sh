#!/usr/bin/env bash
# Prepare a credential-free browser runtime; does not restart or migrate a service.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo 安装浏览器依赖'; exit 2; }
APP_DIR=$(readlink -f "${1:?需要版本目录}")
[[ -f "$APP_DIR/manage.py" && -x "$APP_DIR/.venv/bin/python" ]] || { echo '版本目录无效'; exit 2; }
exec 8>/run/lock/research-workbench-browser-install.lock
flock -n 8 || { echo '已有浏览器安装正在运行，请等待完成。'; exit 2; }
export PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.chromium"
# Each release has its own paths, but identical browser packages share file
# contents through hard links. Removing a release cannot remove another link.
"$APP_DIR/.venv/bin/python" - "$APP_DIR" <<'PY'
import json
import errno
import os
import shutil
import sys
from pathlib import Path
import playwright

target = Path(sys.argv[1]) / '.chromium'
target.mkdir(mode=0o755, exist_ok=True)
manifest = Path(playwright.__file__).parent / 'driver' / 'package' / 'browsers.json'
packages = json.loads(manifest.read_text())['browsers']
needed = set()
for package in packages:
    if package['name'] not in ('chromium-headless-shell', 'ffmpeg'):
        continue
    revisions = {package['revision'], *package.get('revisionOverrides', {}).values()}
    needed.update(package['name'].replace('-', '_') + '-' + str(revision) for revision in revisions)
sources = sorted(Path('/opt/research-workbench-releases').glob('*/.chromium'), reverse=True)
sources.append(Path('/opt/research-workbench/.chromium'))
linked = copied = 0

def reuse_file(source, destination):
    global linked, copied
    # Preserve symlinks separately in copytree. Only root-owned immutable runtime
    # files may be shared; files with other owners get an independent copy.
    metadata = os.stat(source)
    if metadata.st_uid == 0 and not metadata.st_mode & 0o022:
        try:
            os.link(source, destination)
            linked += 1
            return destination
        except OSError as error:
            if error.errno not in (errno.EXDEV, errno.EOPNOTSUPP, errno.EPERM, errno.EMLINK):
                raise
    shutil.copy2(source, destination)
    copied += 1
    return destination

for source in sources:
    if not source.is_dir() or source.resolve() == target.resolve():
        continue
    for name in sorted(needed):
        previous, destination = source / name, target / name
        if destination.exists() or not (previous / 'INSTALLATION_COMPLETE').is_file():
            continue
        # Incomplete copies have a different name and cannot be mistaken for an
        # installed package if this operation is interrupted.
        temporary = target / ('.reuse-' + name)
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(previous, temporary, symlinks=True, copy_function=reuse_file)
        temporary.rename(destination)
        print('复用已完整安装的浏览器组件：' + name, flush=True)
print(f'浏览器文件共用：{linked} 个；独立复制：{copied} 个', flush=True)
PY
# Web reading and the sandbox probe use headless=True without a channel.
# Playwright's headless shell is sufficient; the full GUI Chromium is unused.
"$APP_DIR/.venv/bin/python" -m playwright install --with-deps --only-shell chromium
chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"
bash "$APP_DIR/deploy/configure-browser-sandbox.sh" "$PLAYWRIGHT_BROWSERS_PATH"
runuser -u workbench -- env PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  setpriv --no-new-privs "$APP_DIR/.venv/bin/python" "$APP_DIR/deploy/check_browser_sandbox.py"
# Chromium uses its own sandbox. Never add --no-sandbox as a deployment shortcut.
echo "网页读取运行环境已准备：$PLAYWRIGHT_BROWSERS_PATH"
