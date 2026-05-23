#!/bin/bash
# agent-wiki ops with retry + fallback
# Usage: aw-ops-safe.sh <command>
# Commands: pull-view, maintain, lint, weekly-review

set -euo pipefail

CMD="${1:-}"
REGISTRY="/Users/chao/agent-wiki-data/registry.yaml"
WIKI_ID="main"
VENV="/Users/chao/workspace/agent-wiki/.venv/bin/activate"
MAX_RETRIES=2
RETRY_DELAY=5

source "$VENV"

run_aw() {
    case "$CMD" in
        pull-view)
            aw sync pull-view --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1
            ;;
        maintain)
            aw maintain --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1
            ;;
        lint)
            aw lint --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1
            ;;
        weekly-review)
            aw weekly-review --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1
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

# All retries exhausted — graceful degradation
echo "[FALLBACK] aw $CMD failed after $MAX_RETRIES attempts"
echo "[FALLBACK] agent-wiki sync will be retried on next cycle"
echo "[FALLBACK] Hermes agent continues normally"
exit 0
