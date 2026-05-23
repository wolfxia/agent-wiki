#!/usr/bin/env bash
# aw-weekly-review.sh — agent-wiki weekly review with retry
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

MAX=2
attempt=0
while [ $attempt -lt $MAX ]; do
    attempt=$((attempt + 1))
    if output=$(aw weekly-review --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1); then
        echo "$output"
        exit 0
    else
        echo "[WARN] aw weekly-review failed (attempt $attempt/$MAX)"
        [ $attempt -lt $MAX ] && sleep 5
    fi
done
echo "[FALLBACK] aw weekly-review failed after $MAX attempts, will retry next cycle"
exit 0
