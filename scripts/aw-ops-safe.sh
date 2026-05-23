#!/usr/bin/env bash
# aw-ops-safe.sh — agent-wiki ops with retry + fallback
# Usage: aw-ops-safe.sh <command>
# Commands: pull-view, maintain, lint, weekly-review
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

CMD="${1:-}"
MAX_RETRIES=2
RETRY_DELAY=5

run_aw() {
    case "$CMD" in
        pull-view)
            aw sync pull-view --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1
            ;;
        maintain)
            aw maintain --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1
            ;;
        lint)
            aw lint --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1
            ;;
        weekly-review)
            aw weekly-review --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1
            ;;
        *)
            echo "Unknown command: $CMD"
            return 1
            ;;
    esac
}

attempt=0
while [ $attempt -lt $MAX_RETRIES ]; do
    attempt=$((attempt + 1))
    if output=$(run_aw 2>&1); then
        echo "$output"
        exit 0
    else
        echo "[WARN] aw $CMD failed (attempt $attempt/$MAX_RETRIES)"
        if [ $attempt -lt $MAX_RETRIES ]; then
            sleep $RETRY_DELAY
        fi
    fi
done

echo "[FALLBACK] aw $CMD failed after $MAX_RETRIES attempts"
echo "[FALLBACK] agent-wiki continues normally, will retry on next cycle"
exit 0
