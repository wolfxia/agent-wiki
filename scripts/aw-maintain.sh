#!/bin/bash
# agent-wiki maintain — silent on expected failures, tolerant of slow runs
set -euo pipefail
VENV="/Users/chao/workspace/agent-wiki/.venv/bin/activate"
REGISTRY="/Users/chao/agent-wiki-data/registry.yaml"
ENV_FILE="/Users/chao/agent-wiki-data/.env"
WIKI_ID="main"

source "$VENV" 2>/dev/null

# Load API keys from .env
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Run maintain with 100s timeout using perl (macOS compatible)
# maintain typically takes ~15s, 100s is generous safety margin
output=$(AGENT_WIKI_ACTOR_TYPE=agent AGENT_WIKI_ACTOR_ID=hermes \
  perl -e 'alarm 100; exec @ARGV' -- \
  aw maintain --registry "$REGISTRY" --wiki-id "$WIKI_ID" 2>&1)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    # Extract quality_metrics line if present
    echo "$output" | grep -E "quality_metrics|compile_pending|compile_coverage|synthesis_directions" || true
    echo "[aw-maintain] OK"
    exit 0
fi

# Timeout (142 = SIGALRM) is acceptable — maintain is best-effort
if [ $exit_code -eq 142 ]; then
    echo "[aw-maintain] timeout (acceptable, partial progress)"
    exit 0
fi

# Known bugs — silent fallback
if echo "$output" | grep -q "date is not JSON serializable\|not JSON serializable"; then
    exit 0
fi

# Unknown error — report
echo "[aw-maintain] ERROR: $output"
exit 1
