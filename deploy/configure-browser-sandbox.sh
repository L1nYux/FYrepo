#!/usr/bin/env bash
# Allow only the installed Chromium executables to create their own sandbox.
# See Chromium docs/security/apparmor-userns-restrictions.md (path allowlist).
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo '需要 sudo 配置浏览器沙盒'; exit 2; }
BROWSERS=$(readlink -f "${1:?需要 Playwright 浏览器目录}")
[[ -d "$BROWSERS" && "$BROWSERS" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo '浏览器目录无效'; exit 2; }
case $(basename "$BROWSERS") in .chromium|ms-playwright) ;; *) echo '仅接受独立 Playwright 浏览器目录'; exit 2 ;; esac
if [[ ! -f /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]] ||
   [[ $(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns) != 1 ]]; then
  echo '当前系统允许浏览器使用用户命名空间沙盒。'
  exit 0
fi
[[ -x /sbin/apparmor_parser && -f /etc/apparmor.d/abi/4.0 ]] || { echo '缺少 AppArmor 配置工具或 ABI 4.0'; exit 2; }
mapfile -t EXECUTABLES < <(find "$BROWSERS" -type f \( -name chrome -o -name headless_shell -o -name chrome-headless-shell \) | sort)
[[ ${#EXECUTABLES[@]} -gt 0 ]] || { echo '没有找到 Chromium 可执行文件'; exit 2; }
chown -R root:root "$BROWSERS"
chmod -R go-w "$BROWSERS"
IDENTITY=$(printf '%s' "$BROWSERS" | sha256sum | cut -c1-12)
POLICY=/etc/apparmor.d/workbench-reader-$IDENTITY
TEMP=$(mktemp)
trap 'rm -f -- "$TEMP"' EXIT
printf 'abi <abi/4.0>,\ninclude <tunables/global>\n' > "$TEMP"
for INDEX in "${!EXECUTABLES[@]}"; do
  EXECUTABLE=${EXECUTABLES[$INDEX]}
  [[ "$EXECUTABLE" =~ ^/[a-zA-Z0-9_./-]+$ && -x "$EXECUTABLE" ]] || { echo 'Chromium 可执行路径无效'; exit 2; }
  printf 'profile workbench-reader-%s-%s "%s" flags=(unconfined) {\n  userns,\n}\n' "$IDENTITY" "$INDEX" "$EXECUTABLE" >> "$TEMP"
  echo "配置浏览器沙盒路径：$EXECUTABLE"
done
install -o root -g root -m 0644 "$TEMP" "$POLICY"
/sbin/apparmor_parser -r "$POLICY"
echo '已按安装路径允许 Chromium 建立沙盒；系统全局限制保持开启。'
