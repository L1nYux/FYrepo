#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo'; exit 2; }
RELEASE=$(readlink -f "$1")
DATA=$(readlink -f "$2")
ENV_FILE=$3
[[ -f "$RELEASE/manage.py" && -x "$RELEASE/.venv/bin/python" && -f "$ENV_FILE" && -f "$DATA/workbench.sqlite3" && "$DATA" != / ]] || exit 2
cat > /etc/systemd/system/research-workbench-local-chat.service <<EOF
[Unit]
Description=Prune ordinary chats fully received 30 days ago
After=research-workbench.service
[Service]
Type=oneshot
WorkingDirectory=$RELEASE
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/flock -n -E 75 /run/lock/research-workbench-upgrade.lock /usr/sbin/runuser -u workbench -- $RELEASE/.venv/bin/python $RELEASE/manage.py prune_delivered_chat --apply --limit 500
SuccessExitStatus=75
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$DATA /run/lock
EOF
cat > /etc/systemd/system/research-workbench-local-chat.timer <<'EOF'
[Unit]
Description=Daily delivered ordinary chat retention
[Timer]
OnBootSec=15min
OnUnitActiveSec=1d
RandomizedDelaySec=10min
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now research-workbench-local-chat.timer
