#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo '请以 root 身份运行' >&2
  exit 1
fi
DATA_DIR=/var/lib/research-workbench
BACKUP_DIR=/var/backups/research-workbench
STAMP="$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 "$BACKUP_DIR"
TEMP="$(mktemp -d)"
trap 'rm -rf -- "$TEMP"' EXIT
python3 - "$DATA_DIR/workbench.sqlite3" "$TEMP/workbench.sqlite3" <<'PY'
import sqlite3
import sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
source.backup(target)
target.close()
source.close()
PY
if [[ -d "$DATA_DIR/private_uploads" ]]; then
  cp -a "$DATA_DIR/private_uploads" "$TEMP/private_uploads"
fi
tar -czf "$BACKUP_DIR/$STAMP.tar.gz" -C "$TEMP" .
chmod 0600 "$BACKUP_DIR/$STAMP.tar.gz"
echo "$BACKUP_DIR/$STAMP.tar.gz"
