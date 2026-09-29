#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo '请以 root 身份运行：sudo bash deploy/install.sh' >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR=/var/lib/research-workbench
ENV_FILE=/etc/research-workbench.env

apt-get update
apt-get install -y python3-venv python3-pip
if ! id workbench >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DATA_DIR" --shell /usr/sbin/nologin workbench
fi
install -d -o workbench -g workbench -m 0700 "$DATA_DIR" "$DATA_DIR/private_uploads"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
  cat > "$ENV_FILE" <<EOF
WORKBENCH_SECRET_KEY=$SECRET
WORKBENCH_DATA_DIR=$DATA_DIR
WORKBENCH_ALLOWED_HOSTS=127.0.0.1,localhost
WORKBENCH_DEBUG=0
WORKBENCH_HTTPS=0
EOF
fi
chown root:workbench "$ENV_FILE"
chmod 0640 "$ENV_FILE"
chown -R root:root "$APP_DIR"

set -a
source "$ENV_FILE"
set +a
"$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" collectstatic --noinput
runuser -u workbench -- bash -c "set -a; source '$ENV_FILE'; set +a; exec '$APP_DIR/.venv/bin/python' '$APP_DIR/manage.py' migrate --noinput"

cat > /etc/systemd/system/research-workbench.service <<EOF
[Unit]
Description=Research Workbench
After=network.target

[Service]
Type=simple
User=workbench
Group=workbench
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --threads 2 --timeout 60 --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable research-workbench
systemctl restart research-workbench
echo
echo '应用已安装并仅监听服务器本机 127.0.0.1:8000。'
echo '下一步：创建首个管理员（命令见 README.md），然后通过 SSH 转发访问。'
