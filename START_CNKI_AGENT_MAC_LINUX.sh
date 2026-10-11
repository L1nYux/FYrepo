#!/usr/bin/env bash
set -euo pipefail
exec bash "$(dirname "$0")/tools/cnki_agent/run_agent_mac_linux.sh" "$@"
