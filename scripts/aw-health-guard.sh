#!/bin/bash
# aw-health-guard.sh — agent-wiki 服务健康守卫
# 检测服务可用性，异常时自动修复并告警
set -euo pipefail

VENV="/Users/chao/workspace/agent-wiki/.venv/bin/activate"
REGISTRY="/Users/chao/agent-wiki-data/registry.yaml"
ENV_FILE="/Users/chao/agent-wiki-data/.env"
LOG="/tmp/aw-health-guard.log"

source "$VENV" 2>/dev/null
if [ -f "$ENV_FILE" ]; then set -a; source "$ENV_FILE"; set +a; fi
export AGENT_WIKI_ACTOR_TYPE=agent AGENT_WIKI_ACTOR_ID=hermes AGENT_WIKI_REGISTRY="$REGISTRY"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

# 1. CLI health check (filesystem + index)
health_output=$(aw health --registry "$REGISTRY" 2>&1) || true
if ! echo "$health_output" | grep -q "status=ok"; then
    log "HEALTH_FAIL: $health_output"
    echo "⚠️ agent-wiki health check failed: $health_output"
    exit 1
fi

# 2. MCP query smoke test (verifies MCP server can start and respond)
query_result=$(aw query "test" --registry "$REGISTRY" 2>&1 | head -1) || true
if ! echo "$query_result" | grep -q "hit_count"; then
    log "MCP_QUERY_FAIL: $query_result"
    echo "⚠️ agent-wiki MCP query failed (server may not start): $query_result"
    exit 1
fi

# 3. Check review queue for stale assigned items (indicates crashed compile)
assigned_count=$(python3 -c "
import json
with open('/Users/chao/agent-wiki-data/wiki-1/review_queue.jsonl') as f:
    entries = [json.loads(l) for l in f if l.strip()]
print(sum(1 for e in entries if e.get('item_type') == 'compile_suggestion' and e.get('status') == 'assigned'))
" 2>/dev/null || echo "0")

if [ "$assigned_count" -gt 5 ]; then
    log "STALE_ASSIGNED: $assigned_count items, resetting"
    python3 -c "
import json
path = '/Users/chao/agent-wiki-data/wiki-1/review_queue.jsonl'
with open(path) as f:
    entries = [json.loads(l) for l in f if l.strip()]
changed = 0
for e in entries:
    if e.get('item_type') == 'compile_suggestion' and e.get('status') == 'assigned':
        e['status'] = 'open'
        changed += 1
with open(path, 'w') as f:
    for e in entries:
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
print(f'reset_{changed}')
" 2>/dev/null
    echo "🔄 Reset $assigned_count stale assigned compile items → open"
fi

# All good
log "OK"
exit 0
