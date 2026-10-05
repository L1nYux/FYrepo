#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo'; exit 2; }
RELEASE=$(readlink -f "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}")
DATA=$(readlink -m "${2:-/var/lib/research-workbench}")
ENV_FILE=${3:-/etc/research-workbench.env}
[[ -f "$RELEASE/manage.py" && -x "$RELEASE/.venv/bin/python" && -f "$ENV_FILE" && "$DATA" != / ]] || { echo '应用或数据路径无效'; exit 2; }
cat > /etc/systemd/system/research-workbench-releases.service <<EOF
[Unit]
Description=Workbench stable release announcements
After=network-online.target research-workbench.service
[Service]
Type=oneshot
User=workbench
Group=workbench
WorkingDirectory=$RELEASE
EnvironmentFile=$ENV_FILE
ExecStart=$RELEASE/.venv/bin/python $RELEASE/manage.py publish_release --check-latest
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA
EOF
cat > /etc/systemd/system/research-workbench-releases.timer <<'EOF'
[Unit]
Description=Check Workbench release announcements every 15 minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
RandomizedDelaySec=30s
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now research-workbench-releases.timer
