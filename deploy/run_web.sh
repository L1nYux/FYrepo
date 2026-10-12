#!/usr/bin/env bash
set -euo pipefail
RELEASE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORKERS=${WORKBENCH_WEB_WORKERS:-2}
THREADS=${WORKBENCH_WEB_THREADS:-8}
[[ "$WORKERS" =~ ^[0-9]+$ && "$THREADS" =~ ^[0-9]+$ ]] || { echo 'Web worker/thread counts must be integers.' >&2; exit 2; }
(( WORKERS >= 1 && WORKERS <= 8 && THREADS >= 1 && THREADS <= 64 )) || { echo 'Web worker/thread count is outside the supported range.' >&2; exit 2; }
cd "$RELEASE"
exec "$RELEASE/.venv/bin/gunicorn" config.wsgi:application --bind 127.0.0.1:8000 \
  --workers "$WORKERS" --threads "$THREADS" --timeout 0 --graceful-timeout 270 --error-logfile -
