#!/usr/bin/env bash
# aw-lint.sh — agent-wiki lint with retry
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

MAX=2
attempt=0
while [ $attempt -lt $MAX ]; do
    attempt=$((attempt + 1))
    if output=$(aw lint --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1); then
        echo "$output"
        exit 0
    else
        echo "[WARN] aw lint failed (attempt $attempt/$MAX)"
        [ $attempt -lt $MAX ] && sleep 5
    fi
done
echo "[FALLBACK] aw lint failed after $MAX attempts, will retry next cycle"
exit 0
