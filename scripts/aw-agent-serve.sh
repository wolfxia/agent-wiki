#!/usr/bin/env bash
# aw-agent-serve.sh — start agent-wiki MCP server
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/aw-common.sh
source "$SCRIPT_DIR/aw-common.sh"

cd "$AW_PROJECT_DIR"
exec aw-agent serve --no-pidfile --registry "$AW_REGISTRY"
