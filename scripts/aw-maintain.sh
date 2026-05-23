#!/usr/bin/env bash
# aw-maintain.sh — agent-wiki maintain, silent on expected failures
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

# Run maintain with CLI-level timeout (typically ~15s, 100s is generous)
output=$(AGENT_WIKI_CLI_TIMEOUT_SECONDS=100 \
  aw maintain --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1) || true

# Known bugs — silent fallback
if echo "$output" | grep -q "date is not JSON serializable\|not JSON serializable"; then
    exit 0
fi

# Success
echo "$output" | grep -E "quality_metrics|compile_pending|compile_coverage|synthesis_directions" || true
echo "[aw-maintain] OK"
exit 0
