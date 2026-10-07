#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo'; exit 2; }
RELEASE=$(readlink -f "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}")
DATA=$(readlink -m "${2:-/var/lib/research-workbench}")
ENV_FILE=${3:-/etc/research-workbench.env}
[[ -f "$RELEASE/manage.py" && -x "$RELEASE/.venv/bin/python" && -f "$ENV_FILE" && "$DATA" != / ]] || { echo '应用或数据路径无效'; exit 2; }
cat > /etc/systemd/system/research-workbench-gifts.service <<EOF
[Unit]
Description=Return expired Workbench AI point gifts
After=research-workbench.service
[Service]
Type=oneshot
User=workbench
Group=workbench
WorkingDirectory=$RELEASE
EnvironmentFile=$ENV_FILE
ExecStart=$RELEASE/.venv/bin/python $RELEASE/manage.py expire_point_gifts
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA
EOF
cat > /etc/systemd/system/research-workbench-gifts.timer <<'EOF'
[Unit]
Description=Check expired Workbench point gifts each minute
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=5s
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now research-workbench-gifts.timer
