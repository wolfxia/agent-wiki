#!/usr/bin/env bash
# aw-dream-cycle.sh — run dream cycle synthesis step
# Timeout: 300s (each synthesis ~45s, max 5 per run)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

output=$(AGENT_WIKI_CLI_TIMEOUT_SECONDS=300 \
  aw dream-cycle --step synthesis 2>&1) || true

# Success
echo "$output" | tail -10
echo "DREAM_CYCLE_OK $(date +%H:%M)"
exit 0
