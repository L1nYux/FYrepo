#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo '请以 root 运行：sudo bash deploy/install_sampling_worker.sh' >&2
  exit 1
fi
APP_DIR=$(readlink -f "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}")
ENV_FILE=${3:-/etc/research-workbench.env}
if [[ ! -f "$ENV_FILE" || ! -x "$APP_DIR/.venv/bin/python" ]]; then
  echo '请先完成 FYrepo 安装，并使用既有的环境配置和虚拟环境。' >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
DATA_DIR=$(readlink -m "${2:-${WORKBENCH_DATA_DIR:-/var/lib/research-workbench}}")
[[ "$DATA_DIR" != / ]] || { echo '数据路径无效'; exit 2; }
cat > /etc/systemd/system/research-sampling-worker.service <<SERVICE
[Unit]
Description=FYrepo PDF to Markdown queue
After=research-workbench.service

[Service]
Type=simple
User=workbench
Group=workbench
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/manage.py sampling_worker
Restart=always
RestartSec=3
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
systemctl enable --now research-sampling-worker
echo 'PDF 转换队列已启动。查看日志：journalctl -u research-sampling-worker -f'
