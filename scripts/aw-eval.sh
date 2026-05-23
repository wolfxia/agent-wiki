#!/bin/bash
# aw-eval.sh — agent-wiki retrieval quality eval (cron job)
# Outputs: strict/loose recall@K, must_not violation, precision, MRR
# Exit 0 always (alert only on significant regression)

set -euo pipefail

VENV="/Users/chao/workspace/agent-wiki/.venv/bin/activate"
REGISTRY="/Users/chao/agent-wiki-data/registry.yaml"
ENV_FILE="/Users/chao/agent-wiki-data/.env"
WIKI_ID="main"
EVAL_FILE="eval/retrieval_queries.jsonl"
K=5
HISTORY_DIR="/Users/chao/agent-wiki-data/eval-history"
DATE=$(date +%Y-%m-%d_%H%M)
OUTFILE="${HISTORY_DIR}/${DATE}.json"

mkdir -p "${HISTORY_DIR}"

cd /Users/chao/workspace/agent-wiki
source "$VENV"

# Load API keys from .env
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

export AGENT_WIKI_ACTOR_TYPE=agent
export AGENT_WIKI_ACTOR_ID=hermes

# Run eval with 5-minute timeout
RESULT=$(perl -e 'alarm 300; exec @ARGV' aw eval \
  --wiki-id "${WIKI_ID}" \
  --registry "${REGISTRY}" \
  --eval-file "${EVAL_FILE}" \
  --k "${K}" \
  2>&1) || true

# Save raw result
echo "${RESULT}" > "${OUTFILE}"

# Extract key metrics
STRICT=$(echo "${RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metrics']['strict_recall_at_k'])" 2>/dev/null || echo "PARSE_ERROR")
LOOSE=$(echo "${RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metrics']['loose_recall_at_k'])" 2>/dev/null || echo "PARSE_ERROR")
MUST_NOT=$(echo "${RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metrics']['must_not_violation_at_k'])" 2>/dev/null || echo "PARSE_ERROR")

# Compare with previous baseline
BASELINE_FILE="${HISTORY_DIR}/baseline.json"
if [ -f "${BASELINE_FILE}" ]; then
  PREV_STRICT=$(python3 -c "import json; d=json.load(open('${BASELINE_FILE}')); print(d['metrics']['strict_recall_at_k'])" 2>/dev/null || echo "0")
else
  PREV_STRICT="none"
fi

echo "aw-eval ${DATE}: strict@${K}=${STRICT} loose@${K}=${LOOSE} must_not=${MUST_NOT} prev=${PREV_STRICT}"
