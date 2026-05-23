#!/usr/bin/env bash
# aw-eval.sh — retrieval quality eval (cron job)
# Outputs: strict/loose recall@K, must_not violation, precision, MRR
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

EVAL_FILE="eval/retrieval_queries.jsonl"
K=5
HISTORY_DIR="${AW_DATA_DIR}/eval-history"
DATE=$(date +%Y-%m-%d_%H%M)
OUTFILE="${HISTORY_DIR}/${DATE}.json"

mkdir -p "${HISTORY_DIR}"

# Run eval with 5-minute timeout
RESULT=$(AGENT_WIKI_CLI_TIMEOUT_SECONDS=300 \
  aw eval \
  --wiki-id "${AW_WIKI_ID}" \
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
