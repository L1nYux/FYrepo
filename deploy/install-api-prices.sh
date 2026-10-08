#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo'; exit 2; }
APP_DIR=$(readlink -f "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}")
DATA=$(readlink -m "${2:-/var/lib/research-workbench}")
ENV_FILE=${3:-/etc/research-workbench.env}
[[ -f "$APP_DIR/manage.py" && -x "$APP_DIR/.venv/bin/python" && -f "$ENV_FILE" && "$DATA" != / ]] || { echo '应用或数据路径无效'; exit 2; }
cat > /etc/systemd/system/research-workbench-prices.service <<EOF
[Unit]
Description=Research Workbench daily API prices
After=network-online.target

[Service]
Type=oneshot
User=workbench
Group=workbench
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/manage.py refresh_api_prices
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA
EOF
cat > /etc/systemd/system/research-workbench-prices.timer <<'EOF'
[Unit]
Description=Daily API price refresh

[Timer]
OnCalendar=*-*-* 00:15:00 Asia/Shanghai
OnBootSec=2min
Persistent=true
RandomizedDelaySec=60
Unit=research-workbench-prices.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now research-workbench-prices.timer
