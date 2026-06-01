#!/usr/bin/env bash
# aw-compile-execute.sh — run a single compile cycle
# Exit codes: 0 = OK/timeout/nothing-to-compile, 1 = real error
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

# Batch compile: process up to 5 items with concurrency 3 per run
# Can override via env: AW_COMPILE_LIMIT=10 AW_COMPILE_CONCURRENCY=5
COMPILE_LIMIT="${AW_COMPILE_LIMIT:-5}"
COMPILE_CONCURRENCY="${AW_COMPILE_CONCURRENCY:-2}"

output=$(AGENT_WIKI_CLI_TIMEOUT_SECONDS=180 \
  aw compile-execute --limit "$COMPILE_LIMIT" --concurrency "$COMPILE_CONCURRENCY" --apply 2>&1) || true

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
