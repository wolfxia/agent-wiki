#!/usr/bin/env bash
set -euo pipefail

cd ~/workspace/agent-wiki && source .venv/bin/activate

ENV_FILE="${AGENT_WIKI_ENV_FILE:-$HOME/agent-wiki-data/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

export AGENT_WIKI_ACTOR_TYPE=agent
export AGENT_WIKI_ACTOR_ID=hermes
export AGENT_WIKI_REGISTRY=/Users/chao/agent-wiki-data/registry.yaml

# Dream cycle synthesis step — generates cross-domain synthesis pages
# Timeout: 300s (each synthesis takes ~45s, max 5 per run)
output=$(perl -e 'alarm 300; exec @ARGV' -- \
  aw dream-cycle --step synthesis 2>&1)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "$output" | tail -10
    echo "DREAM_CYCLE_OK $(date +%H:%M)"
    exit 0
fi

# Timeout (142 = SIGALRM) is acceptable — partial progress is fine
if [ $exit_code -eq 142 ]; then
    echo "$output" | tail -5
    echo "DREAM_CYCLE_TIMEOUT $(date +%H:%M)"
    exit 0
fi

# Real error — report
echo "DREAM_CYCLE_ERROR: $output" | tail -5
exit 1
