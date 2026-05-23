#!/bin/bash
# agent-wiki pull-view sync — silent on expected failures
set -euo pipefail
VENV="/Users/chao/workspace/agent-wiki/.venv/bin/activate"
REGISTRY="/Users/chao/agent-wiki-data/registry.yaml"
ENV_FILE="/Users/chao/agent-wiki-data/.env"
WIKI_ID="main"

source "$VENV" 2>/dev/null

# Load API keys from .env
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

output=$(AGENT_WIKI_ACTOR_TYPE=agent AGENT_WIKI_ACTOR_ID=hermes \
  aw sync pull-view --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    # Success — only report if there are changes
    changed=$(echo "$output" | grep -c "^mode=" || true)
    if [ "$changed" -gt 0 ]; then
        echo "[aw-pull-view] sync completed"
    fi
    exit 0
fi

# Known bug: date serialization in sync — silent fallback
if echo "$output" | grep -q "date is not JSON serializable"; then
    exit 0
fi

# Unknown error — report
echo "[aw-pull-view] ERROR: $output"
exit 1
