#!/usr/bin/env bash
# aw-dream-cycle.sh — run dream cycle one step at a time
# Cron default timeout is 120s; synthesis alone takes ~140s, so we run steps separately.
# Schedule 3 separate cron jobs for orphan/cross-ref/synthesis, each stays under 120s.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

STEP="${1:-synthesis}"

output=$(aw dream-cycle --step "$STEP" 2>&1) || true

# Summary output (keep under 1KB for cron)
case "$STEP" in
  orphan)
    echo "$output" | grep -oP 'orphan_count=\d+' | tail -1
    ;;
  cross-ref)
    echo "$output" | grep -oP 'candidate_group_count=\d+' | tail -1
    ;;
  synthesis)
    echo "$output" | grep -oP 'synthesis_count=\d+' | tail -1
    ;;
esac
echo "DREAM_CYCLE_${STEP^^}_OK $(date +%H:%M)"
exit 0
