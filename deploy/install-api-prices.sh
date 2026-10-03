#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cat > /etc/systemd/system/research-workbench-prices.service <<EOF
[Unit]
Description=Research Workbench daily API prices
After=network-online.target

[Service]
Type=oneshot
User=workbench
Group=workbench
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/research-workbench.env
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/manage.py refresh_api_prices
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/research-workbench
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
