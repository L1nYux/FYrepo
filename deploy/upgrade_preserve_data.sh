#!/usr/bin/env bash
# Stage a release first; --apply is the explicit production cutover.
set -euo pipefail
MODE=${1:---prepare}
[[ "$MODE" == --prepare || "$MODE" == --apply ]] || { echo '用法：sudo bash deploy/upgrade_preserve_data.sh --prepare|--apply'; exit 2; }
[[ $(id -u) == 0 ]] || { echo '需要 sudo'; exit 2; }
SOURCE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=/etc/research-workbench.env
SERVICE=research-workbench
[[ -f "$ENV_FILE" ]] || { echo '缺少现有环境配置，请先确认服务器安装路径'; exit 2; }
set -a
source "$ENV_FILE"
set +a
DATA=$(readlink -m "${WORKBENCH_DATA_DIR:-/var/lib/research-workbench}")
[[ "$DATA" != / && "$DATA" != /var && "$DATA" != /var/lib && -f "$DATA/workbench.sqlite3" ]] || { echo '数据路径无效或没有旧数据库'; exit 2; }
STAMP=$(date +%Y%m%d-%H%M%S)
RELEASE=/opt/research-workbench-releases/$STAMP
BACKUP=/var/backups/research-workbench/upgrade-$STAMP
STAGE=$RELEASE/.upgrade-check-data
DROPIN=/etc/systemd/system/research-workbench.service.d/90-release.conf
PRICE_SERVICE=/etc/systemd/system/research-workbench-prices.service
install -d -m 0755 "$RELEASE"
install -d -m 0700 "$BACKUP" "$STAGE"
cp -a "$ENV_FILE" "$BACKUP/environment.env"
systemctl cat "$SERVICE" > "$BACKUP/service-before.txt"
[[ ! -f "$DROPIN" ]] || cp -a "$DROPIN" "$BACKUP/90-release.conf"
[[ ! -f "$PRICE_SERVICE" ]] || cp -a "$PRICE_SERVICE" "$BACKUP/prices.service"
# Only tracked application directories are copied; no preview data or desktop runtime.
for item in manage.py requirements.txt config core aihub templates static deploy; do
  [[ ! -e "$SOURCE/$item" ]] || cp -a "$SOURCE/$item" "$RELEASE/"
done
find "$RELEASE" -type d -name __pycache__ -prune -exec rm -rf -- {} +
python3 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/python" -m pip install -r "$RELEASE/requirements.txt"
snapshot() {
  "$RELEASE/.venv/bin/python" - "$DATA/workbench.sqlite3" "$1" <<'PY'
import sqlite3, sys
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
PY
}
snapshot "$STAGE/workbench.sqlite3"
"$RELEASE/.venv/bin/python" "$RELEASE/deploy/preflight_database.py" "$STAGE/workbench.sqlite3"
chown -R root:root "$RELEASE"
chown -R workbench:workbench "$STAGE"
# Use an isolated copy to detect migration conflicts before stopping production.
runuser -u workbench -- env WORKBENCH_DATA_DIR="$STAGE" "$RELEASE/.venv/bin/python" "$RELEASE/manage.py" migrate --noinput
"$RELEASE/.venv/bin/python" "$RELEASE/manage.py" collectstatic --noinput
if [[ "$MODE" == --prepare ]]; then
  echo "准备完成：$RELEASE。现有服务、数据库和账户没有改动。"
  echo '正式升级请在服务器操作获准后，从相同源码执行 --apply；会再次准备并备份最新数据。'
  exit 0
fi
timer_active=0
systemctl is-active --quiet research-workbench-prices.timer && timer_active=1
systemctl stop research-workbench-prices.timer research-workbench-prices.service 2>/dev/null || true
stopped=0
rollback() {
  code=$?
  trap - ERR
  if [[ "$stopped" == 1 ]]; then
    systemctl stop "$SERVICE" || true
    if [[ -f "$BACKUP/workbench.sqlite3" ]]; then
      cp -a "$BACKUP/workbench.sqlite3" "$DATA/workbench.sqlite3"
      rm -f -- "$DATA/workbench.sqlite3-wal" "$DATA/workbench.sqlite3-shm"
      chown workbench:workbench "$DATA/workbench.sqlite3"
    fi
    if [[ -f "$BACKUP/90-release.conf" ]]; then cp -a "$BACKUP/90-release.conf" "$DROPIN"; else rm -f -- "$DROPIN"; fi
    if [[ -f "$BACKUP/prices.service" ]]; then cp -a "$BACKUP/prices.service" "$PRICE_SERVICE"; else rm -f -- "$PRICE_SERVICE"; fi
    systemctl daemon-reload
    systemctl start "$SERVICE" || true
  fi
  [[ "$timer_active" == 0 ]] || systemctl start research-workbench-prices.timer || true
  echo "升级失败，已尝试恢复旧版本。备份：$BACKUP" >&2
  exit "$code"
}
trap rollback ERR
systemctl stop "$SERVICE"
stopped=1
# No writers remain: this backup is the production rollback point.
snapshot "$BACKUP/workbench.sqlite3"
chmod 0600 "$BACKUP/workbench.sqlite3"
tar -czf "$BACKUP/data-and-keys.tar.gz" -C "$DATA" .
chmod 0600 "$BACKUP/data-and-keys.tar.gz"
"$RELEASE/.venv/bin/python" "$RELEASE/deploy/preflight_database.py" "$DATA/workbench.sqlite3"
runuser -u workbench -- "$RELEASE/.venv/bin/python" "$RELEASE/manage.py" migrate --noinput
install -d -m 0755 "$(dirname "$DROPIN")"
cat > "$DROPIN" <<EOF
[Service]
WorkingDirectory=$RELEASE
ExecStart=
ExecStart=$RELEASE/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --threads 2 --timeout 60 --error-logfile -
ReadWritePaths=$DATA
EOF
cat > "$PRICE_SERVICE" <<EOF
[Unit]
Description=Research Workbench daily API prices
After=network-online.target
[Service]
Type=oneshot
User=workbench
Group=workbench
WorkingDirectory=$RELEASE
EnvironmentFile=$ENV_FILE
ExecStart=$RELEASE/.venv/bin/python $RELEASE/manage.py refresh_api_prices
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DATA
EOF
systemctl daemon-reload
systemctl start "$SERVICE"
"$RELEASE/.venv/bin/python" - <<'PY'
import json, os, time, urllib.request
allowed = [v.strip() for v in os.environ.get('WORKBENCH_ALLOWED_HOSTS', '127.0.0.1').split(',') if v.strip()]
host = next((v for v in allowed if v != '*' and not v.startswith('.')), '127.0.0.1')
for attempt in range(10):
    try:
        request = urllib.request.Request('http://127.0.0.1:8000/desktop/api/status/', headers={'Host': host})
        value = json.load(urllib.request.urlopen(request, timeout=5))
        if value.get('protocol') == 1 and not value.get('authenticated'):
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit('桌面连接接口尚未就绪')
PY
[[ "$timer_active" == 0 ]] || systemctl start research-workbench-prices.timer
trap - ERR
echo "升级完成。原有账户、密码、业务数据库、附件和 API Key 已保留。备份：$BACKUP"
echo "运行中的版本目录：$RELEASE；旧代码仍在原目录。"
