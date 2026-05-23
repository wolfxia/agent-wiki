#!/bin/bash
# agent-wiki weekly-review
set -euo pipefail
VENV="/Users/chao/workspace/agent-wiki/.venv/bin/activate"
REGISTRY="/Users/chao/agent-wiki-data/registry.yaml"
ENV_FILE="/Users/chao/agent-wiki-data/.env"
WIKI_ID="main"

source "$VENV"

# Load API keys from .env
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

attempt=0
MAX=2
while [ $attempt -lt $MAX ]; do
    attempt=$((attempt + 1))
    if output=$(AGENT_WIKI_ACTOR_TYPE=agent AGENT_WIKI_ACTOR_ID=hermes \
      aw weekly-review --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1); then
        echo "$output"
        exit 0
    else
        echo "[WARN] aw weekly-review failed (attempt $attempt/$MAX)"
        [ $attempt -lt $MAX ] && sleep 5
    fi
done
echo "[FALLBACK] aw weekly-review failed after $MAX attempts, will retry next cycle"
exit 0
