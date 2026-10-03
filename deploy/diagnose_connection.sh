#!/usr/bin/env bash
# Read-only diagnosis: no environment secrets or account data are printed.
set -u
HOST=${1:-47.117.89.248}
[[ "$HOST" =~ ^[a-zA-Z0-9.-]+$ ]] || exit 2
systemctl is-active research-workbench nginx || true
curl --noproxy '*' --max-time 10 -sS -o /dev/null -w '后端接口 HTTP %{http_code}\n' -H "Host: $HOST" http://127.0.0.1:8000/desktop/api/status/ || true
curl --noproxy '*' --max-time 10 -sS -o /dev/null -w 'Nginx 入口 HTTP %{http_code}\n' -H "Host: $HOST" http://127.0.0.1/desktop/api/status/ || true
ss -ltn '( sport = :80 or sport = :443 or sport = :8000 )'
