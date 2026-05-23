#!/usr/bin/env bash
# aw-common.sh — shared configuration for agent-wiki scripts
# Sourced by all aw-* scripts. DO NOT execute directly.
#
# Path resolution order (highest priority first):
#   1. Environment variables (AW_PROJECT_DIR, AW_DATA_DIR, AW_REGISTRY)
#   2. Deploy config file (~/.config/agent-wiki/config.sh)
#   3. Auto-detection from script location
#
# Cross-platform: macOS / Linux / WSL / Git Bash on Windows
# Requires: bash 3.2+, aw CLI installed in venv

# --- Auto-detect project root from script location ---
_aw_common_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AW_PROJECT_DIR="${AW_PROJECT_DIR:-$(cd "$_aw_common_dir/.." && pwd)}"
AW_DATA_DIR="${AW_DATA_DIR:-$HOME/agent-wiki-data}"
AW_REGISTRY="${AW_REGISTRY:-$AW_DATA_DIR/registry.yaml}"
AW_VENV="${AW_VENV:-$AW_PROJECT_DIR/.venv}"
AW_WIKI_ID="${AW_WIKI_ID:-main}"
AW_ACTOR_TYPE="${AW_ACTOR_TYPE:-agent}"
AW_ACTOR_ID="${AW_ACTOR_ID:-hermes}"
AW_ENV_FILE="${AW_ENV_FILE:-$AW_DATA_DIR/.env}"

# --- Load deploy config if exists (overrides defaults above) ---
AW_CONFIG_FILE="${AW_CONFIG_FILE:-$HOME/.config/agent-wiki/config.sh}"
if [ -f "$AW_CONFIG_FILE" ]; then
    # shellcheck source=/dev/null
    source "$AW_CONFIG_FILE"
fi

# --- Prefer this project's venv over any aw already on PATH ---
if [ -f "$AW_VENV/bin/activate" ]; then
    source "$AW_VENV/bin/activate"
elif ! command -v aw &>/dev/null; then
    echo "[aw-common] ERROR: aw CLI not found and venv missing at $AW_VENV" >&2
    exit 1
fi

# --- Load API keys from .env ---
if [ -f "$AW_ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$AW_ENV_FILE"
    set +a
fi

# --- Export identity env vars for aw CLI ---
export AGENT_WIKI_ACTOR_TYPE="$AW_ACTOR_TYPE"
export AGENT_WIKI_ACTOR_ID="$AW_ACTOR_ID"
export AGENT_WIKI_REGISTRY="$AW_REGISTRY"

# --- Cross-platform timeout ---
# aw CLI supports AGENT_WIKI_CLI_TIMEOUT_SECONDS natively.
# For scripts that need process-level timeout, use _aw_timeout SECONDS COMMAND...
_aw_timeout() {
    local seconds=$1; shift
    if command -v timeout &>/dev/null; then
        # Linux / coreutils
        timeout "$seconds" "$@"
    elif command -v gtimeout &>/dev/null; then
        # macOS with coreutils (brew install coreutils)
        gtimeout "$seconds" "$@"
    else
        # Fallback: aw CLI handles its own timeout via AGENT_WIKI_CLI_TIMEOUT_SECONDS
        AGENT_WIKI_CLI_TIMEOUT_SECONDS=$seconds "$@"
    fi
}
