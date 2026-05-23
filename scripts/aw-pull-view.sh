#!/usr/bin/env bash
# aw-pull-view.sh — agent-wiki Obsidian pull-view sync, silent on expected failures
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

output=$(aw sync pull-view --registry "$AW_REGISTRY" --wiki-id "$AW_WIKI_ID" 2>&1) || true

# Known bug: date serialization in sync — silent fallback
if echo "$output" | grep -q "date is not JSON serializable"; then
    exit 0
fi

# Success — only report if there are changes
changed=$(echo "$output" | grep -c "^mode=" || true)
if [ "$changed" -gt 0 ]; then
    echo "[aw-pull-view] sync completed"
fi
exit 0
