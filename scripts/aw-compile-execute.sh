#!/usr/bin/env bash
# aw-compile-execute.sh — run a single compile cycle
# Exit codes: 0 = OK/timeout/nothing-to-compile, 1 = real error
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

# Single compile per run, use aw CLI's built-in timeout
output=$(AGENT_WIKI_CLI_TIMEOUT_SECONDS=100 \
  aw compile-execute --limit 1 --concurrency 1 --apply 2>&1) || true

# No items — silent
if echo "$output" | grep -q "无待编译\|no.*compile\|Nothing to\|0 items"; then
    exit 0
fi

# Known issues — silent
if echo "$output" | grep -q "date is not JSON serializable\|not JSON serializable"; then
    exit 0
fi

# Success
if [ $? -eq 0 ] 2>/dev/null; then
    echo "$output" | tail -3
    echo "COMPILE_OK $(date +%H:%M)"
    exit 0
fi

# Real error
echo "COMPILE_ERROR: $output" | tail -5
exit 1
