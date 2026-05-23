#!/bin/bash
set -euo pipefail
cd /Users/chao/workspace/agent-wiki
source .venv/bin/activate

# Load API keys
if [ -f /Users/chao/agent-wiki-data/.env ]; then
    set -a
    source /Users/chao/agent-wiki-data/.env
    set +a
fi

export AGENT_WIKI_ACTOR_TYPE=agent
export AGENT_WIKI_ACTOR_ID=hermes
export AGENT_WIKI_REGISTRY=/Users/chao/agent-wiki-data/registry.yaml

exec aw-agent serve --no-pidfile --registry /Users/chao/agent-wiki-data/registry.yaml
