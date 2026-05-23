#!/usr/bin/env bash
# aw-health-guard.sh — agent-wiki service health guard
# Detects service issues, auto-repairs when possible, alerts on failure
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

LOG="${TMPDIR:-/tmp}/aw-health-guard.log"
log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

# 1. CLI health check (filesystem + index)
health_output=$(aw health --registry "$AW_REGISTRY" 2>&1) || true
if ! echo "$health_output" | grep -q "status=ok"; then
    log "HEALTH_FAIL: $health_output"
    echo "⚠️ agent-wiki health check failed: $health_output"
    exit 1
fi

# 2. MCP query smoke test
query_result=$(aw query "test" --registry "$AW_REGISTRY" 2>&1 | head -1) || true
if ! echo "$query_result" | grep -q "hit_count"; then
    log "MCP_QUERY_FAIL: $query_result"
    echo "⚠️ agent-wiki MCP query failed (server may not start): $query_result"
    exit 1
fi

# 3. Check review queue for stale assigned items
review_queue="${AW_DATA_DIR}/wiki-1/review_queue.jsonl"
if [ -f "$review_queue" ]; then
    assigned_count=$(python3 -c "
import json
with open('$review_queue') as f:
    entries = [json.loads(l) for l in f if l.strip()]
print(sum(1 for e in entries if e.get('item_type') == 'compile_suggestion' and e.get('status') == 'assigned'))
" 2>/dev/null || echo "0")

    if [ "$assigned_count" -gt 5 ]; then
        log "STALE_ASSIGNED: $assigned_count items, resetting"
        python3 -c "
import json
with open('$review_queue') as f:
    entries = [json.loads(l) for l in f if l.strip()]
changed = 0
for e in entries:
    if e.get('item_type') == 'compile_suggestion' and e.get('status') == 'assigned':
        e['status'] = 'open'
        changed += 1
with open('$review_queue', 'w') as f:
    for e in entries:
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
print(f'reset_{changed}')
" 2>/dev/null
        echo "🔄 Reset $assigned_count stale assigned compile items → open"
    fi
fi

# All good
log "OK"
exit 0
