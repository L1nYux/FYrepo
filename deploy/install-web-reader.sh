#!/usr/bin/env bash
# Prepare a credential-free browser runtime; does not restart or migrate a service.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo 安装浏览器依赖'; exit 2; }
APP_DIR=$(readlink -f "${1:?需要版本目录}")
[[ -f "$APP_DIR/manage.py" && -x "$APP_DIR/.venv/bin/python" ]] || { echo '版本目录无效'; exit 2; }
export PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.chromium"
"$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium
chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"
# Chromium uses its own sandbox. Never add --no-sandbox as a deployment shortcut.
echo "网页读取运行环境已准备：$PLAYWRIGHT_BROWSERS_PATH"
