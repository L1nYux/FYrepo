#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo 安装 Office 预览组件'; exit 2; }
APP_DIR=$(readlink -f "${1:?需要应用目录}")
[[ -f "$APP_DIR/deploy/check_office_preview.py" && -x "$APP_DIR/.venv/bin/python" ]] || exit 2
apt-get update
apt-get install -y --no-install-recommends libreoffice-writer bubblewrap fonts-noto-cjk
if [[ -f /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]] &&
   [[ $(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns) == 1 ]]; then
  if [[ -f /etc/apparmor.d/bwrap ]]; then
    /sbin/apparmor_parser -r /etc/apparmor.d/bwrap
  else
    [[ -x /sbin/apparmor_parser && -f /etc/apparmor.d/abi/4.0 ]] || exit 2
    cat > /etc/apparmor.d/workbench-office-bwrap <<'POLICY'
abi <abi/4.0>,
include <tunables/global>
profile workbench-office-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
POLICY
    chmod 0644 /etc/apparmor.d/workbench-office-bwrap
    /sbin/apparmor_parser -r /etc/apparmor.d/workbench-office-bwrap
  fi
fi
runuser -u workbench -- setpriv --no-new-privs "$APP_DIR/.venv/bin/python" "$APP_DIR/deploy/check_office_preview.py"
echo '已安装隔离的 Office 文档预览组件。'
