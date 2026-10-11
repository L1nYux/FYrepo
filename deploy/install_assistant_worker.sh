#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '请使用 sudo 安装助手后台服务。' >&2; exit 1; }
APP_DIR=$(readlink -f "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}")
DATA_DIR=$(readlink -m "${2:-/var/lib/research-workbench}")
ENV_FILE=${3:-/etc/research-workbench.env}
[[ "$DATA_DIR" != / && -f "$ENV_FILE" && -x "$APP_DIR/.venv/bin/python" ]] || { echo '应用、数据目录或环境配置无效。' >&2; exit 2; }
cat > /etc/systemd/system/research-assistant-worker.service <<SERVICE
[Unit]
Description=Zhiyu assistant execution queue
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=workbench
Group=workbench
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=WORKBENCH_ASSISTANT_WORKER=external
Environment=PLAYWRIGHT_BROWSERS_PATH=$APP_DIR/.chromium
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/manage.py assistant_worker --concurrency 2
Restart=always
RestartSec=3
TimeoutStopSec=300
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA_DIR
MemoryMax=512M

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
[[ ${4:-} != --write-only ]] || exit 0
systemctl enable --now research-assistant-worker
