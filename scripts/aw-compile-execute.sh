#!/usr/bin/env bash
set -euo pipefail

cd ~/workspace/agent-wiki && source .venv/bin/activate

# Load API keys
ENV_FILE="${AGENT_WIKI_ENV_FILE:-$HOME/agent-wiki-data/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

export AGENT_WIKI_ACTOR_TYPE=agent
export AGENT_WIKI_ACTOR_ID=hermes
export AGENT_WIKI_REGISTRY=/Users/chao/agent-wiki-data/registry.yaml

# Single compile per run (~86s typically, occasionally >120s)
# alarm 100s leaves 20s margin for Hermes no_agent=true 120s hard limit
output=$(perl -e 'alarm 100; exec @ARGV' -- \
  aw compile-execute --limit 1 --concurrency 1 --apply 2>&1)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "$output" | tail -3
    echo "COMPILE_OK $(date +%H:%M)"
    exit 0
fi

# Timeout (142 = SIGALRM) — partial progress is fine
if [ $exit_code -eq 142 ]; then
    echo "$output" | tail -3
    echo "COMPILE_TIMEOUT $(date +%H:%M)"
    exit 0
fi

# Known issues — silent
if echo "$output" | grep -q "date is not JSON serializable\|not JSON serializable"; then
    exit 0
fi

# No items — silent
if echo "$output" | grep -q "无待编译\|no.*compile\|Nothing to\|0 items"; then
    exit 0
fi

# Real error
echo "COMPILE_ERROR: $output" | tail -5
exit 1
