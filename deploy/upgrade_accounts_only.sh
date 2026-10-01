#!/usr/bin/env bash
# Run only after the merged preview is approved. Old business data stays in backup.
set -euo pipefail
[[ "${1:-}" == '--apply-accounts-only' ]] || { echo '用法：sudo bash deploy/upgrade_accounts_only.sh --apply-accounts-only'; exit 2; }
[[ $(id -u) == 0 ]] || { echo '需要 root 权限'; exit 2; }
RELEASE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP=/opt/research-workbench
ENV=/etc/research-workbench.env
SERVICE=research-workbench
[[ "$RELEASE" != "$APP" ]] || { echo '请将升级包解压到独立目录后执行'; exit 2; }
[[ -x "$APP/.venv/bin/python" && -f "$ENV" ]] || { echo '现有安装不存在'; exit 2; }
set -a
source "$ENV"
set +a
[[ "${WORKBENCH_DATA_DIR:-}" == /var/lib/research-workbench ]] || { echo '数据目录与默认安装不同，请运维确认路径后升级'; exit 2; }
DATA=$WORKBENCH_DATA_DIR
[[ -f "$DATA/workbench.sqlite3" ]] || { echo '旧数据库不存在'; exit 2; }
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=/var/backups/research-workbench/upgrade-$STAMP
NEXT=/opt/research-workbench-next-$STAMP
NEXT_DATA=/var/lib/research-workbench-next-$STAMP
install -d -m 0700 "$BACKUP" "$NEXT_DATA"
install -d -m 0755 "$NEXT"
cp -a "$ENV" "$BACKUP/environment.env"
systemctl cat "$SERVICE" > "$BACKUP/service.txt"
tar --exclude=.git --exclude=.venv --exclude=data --exclude=staticfiles --exclude=__pycache__ -C "$RELEASE" -cf - . | tar -C "$NEXT" -xf -
PYTHON=$APP/.venv/bin/python
# The integration adds no Python dependencies. Do not upgrade the live environment.
WORKBENCH_DATA_DIR="$NEXT_DATA" "$PYTHON" "$NEXT/manage.py" migrate --noinput
WORKBENCH_DATA_DIR="$NEXT_DATA" "$PYTHON" "$NEXT/manage.py" collectstatic --noinput
stopped=0
old_app_moved=0
old_data_moved=0
new_app_installed=0
new_data_installed=0
venv_moved=0
rollback() {
  code=$?
  trap - ERR
  if [[ $stopped == 1 ]]; then
    systemctl stop "$SERVICE" || true
    [[ $new_app_installed == 0 ]] || mv "$APP" "$BACKUP/failed-new-code"
    [[ $new_data_installed == 0 ]] || mv "$DATA" "$BACKUP/failed-new-data"
    if [[ $venv_moved == 1 ]]; then
      if [[ $new_app_installed == 1 ]]; then
        mv "$BACKUP/failed-new-code/.venv" "$BACKUP/code/.venv"
      else
        mv "$NEXT/.venv" "$BACKUP/code/.venv"
      fi
    fi
    [[ $old_app_moved == 0 ]] || mv "$BACKUP/code" "$APP"
    [[ $old_data_moved == 0 ]] || mv "$BACKUP/data" "$DATA"
    systemctl start "$SERVICE" || true
  fi
  echo "升级失败；备份和诊断位置：$BACKUP" >&2
  exit "$code"
}
trap rollback ERR
systemctl stop "$SERVICE"
stopped=1
# Import the account hashes only after writes have stopped.
WORKBENCH_DATA_DIR="$NEXT_DATA" "$PYTHON" "$NEXT/manage.py" import_accounts --source "$DATA/workbench.sqlite3"
chown -R workbench:workbench "$NEXT_DATA"
chmod 0700 "$NEXT_DATA"
chown -R root:root "$NEXT"
mv "$APP" "$BACKUP/code"
old_app_moved=1
# Retain the existing venv at its original path after the directory swap.
mv "$BACKUP/code/.venv" "$NEXT/.venv"
venv_moved=1
mv "$DATA" "$BACKUP/data"
old_data_moved=1
mv "$NEXT" "$APP"
new_app_installed=1
mv "$NEXT_DATA" "$DATA"
new_data_installed=1
systemctl start "$SERVICE"
for attempt in 1 2 3 4 5; do
  if curl -fsS --max-time 5 -H 'Host: 127.0.0.1' http://127.0.0.1:8000/ >/dev/null; then
    trap - ERR
    echo "升级完成。旧代码和业务数据保存在 $BACKUP；账号和密码已保留。"
    exit 0
  fi
  sleep 1
done
false
