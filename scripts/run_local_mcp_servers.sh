#!/usr/bin/env bash
#
# Runs all four MCP servers locally in the foreground (not via Docker), for
# local development. Ctrl+C stops all of them together.
#
# Equivalent to running each of these in separate terminals:
#   make mcp-calendar / make mcp-email / make mcp-tasks
#   python -m app.mcp.servers.web_search_server
#
# Requires: Redis running locally (`make up`). Calendar/email will start
# fine without Google auth configured, but their tools will only succeed
# once GOOGLE_CLIENT_ID/SECRET are set in .env and a user has completed the
# OAuth flow (GET /auth/login) — see README.md.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
if command -v redis-cli > /dev/null 2>&1 && ! redis-cli -u "$REDIS_URL" ping > /dev/null 2>&1; then
    echo "Warning: could not reach Redis at $REDIS_URL" >&2
    echo "  tasks_server and the approval flow need it — run 'make up' first." >&2
    echo
fi

declare -a PIDS=()
CLEANED_UP=false

cleanup() {
    if [ "$CLEANED_UP" = true ]; then
        return
    fi
    CLEANED_UP=true
    echo
    echo "Stopping MCP servers..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
# EXIT is the fallback (e.g. an error under `set -e`); INT/TERM (Ctrl+C, or
# a supervisor stopping this process) explicitly exit afterward so the EXIT
# trap doesn't fire cleanup a second time — the CLEANED_UP guard above would
# make a second call a no-op anyway, but this avoids it running at all.
trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

start_server() {
    local name="$1"
    local module="$2"
    python3 -m "$module" &
    local pid=$!
    PIDS+=("$pid")
    echo "Started $name (pid $pid)"
}

start_server "calendar_server (port 9001)"   "app.mcp.servers.calendar_server"
start_server "email_server (port 9002)"      "app.mcp.servers.email_server"
start_server "tasks_server (port 9003)"      "app.mcp.servers.tasks_server"
start_server "web_search_server (port 9004)" "app.mcp.servers.web_search_server"

echo
echo "All MCP servers running. Press Ctrl+C to stop."
wait