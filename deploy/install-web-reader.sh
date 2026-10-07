#!/usr/bin/env bash
# Prepare a credential-free browser runtime; does not restart or migrate a service.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo 安装浏览器依赖'; exit 2; }
APP_DIR=$(readlink -f "${1:?需要版本目录}")
[[ -f "$APP_DIR/manage.py" && -x "$APP_DIR/.venv/bin/python" ]] || { echo '版本目录无效'; exit 2; }
exec 8>/run/lock/research-workbench-browser-install.lock
flock -n 8 || { echo '已有浏览器安装正在运行，请等待完成。'; exit 2; }
export PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.chromium"
# Each release keeps its own runtime. Reuse only complete, matching revisions
# from older releases; never move or modify the browser used by the live service.
"$APP_DIR/.venv/bin/python" - "$APP_DIR" <<'PY'
import json
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
    if package['name'] not in ('chromium', 'chromium-headless-shell', 'ffmpeg'):
        continue
    revisions = {package['revision'], *package.get('revisionOverrides', {}).values()}
    needed.update(package['name'].replace('-', '_') + '-' + str(revision) for revision in revisions)
sources = sorted(Path('/opt/research-workbench-releases').glob('*/.chromium'), reverse=True)
sources.append(Path('/opt/research-workbench/.chromium'))
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
        shutil.copytree(previous, temporary)
        temporary.rename(destination)
        print('复用已完整安装的浏览器组件：' + name, flush=True)
PY
"$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium
chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"
bash "$APP_DIR/deploy/configure-browser-sandbox.sh" "$PLAYWRIGHT_BROWSERS_PATH"
runuser -u workbench -- env PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  setpriv --no-new-privs "$APP_DIR/.venv/bin/python" "$APP_DIR/deploy/check_browser_sandbox.py"
# Chromium uses its own sandbox. Never add --no-sandbox as a deployment shortcut.
echo "网页读取运行环境已准备：$PLAYWRIGHT_BROWSERS_PATH"
