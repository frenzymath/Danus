#!/usr/bin/env bash
# =============================================================================
# EXAMPLE, NOT CORE. Copy-pasteable demonstration of running Danus unattended.
# Nothing in the engine depends on examples/. See examples/README.md.
# =============================================================================
# main-agent-tmux.sh — run codex as a resident main agent inside tmux.
#
# This is the ONLY unattended mode in Danus: a long-lived codex session in the
# repo root. Because it starts in DANUS_ROOT it inherits the repo's AGENTS.md,
# its skills (.agents/skills), and .codex/config.toml — which wires the
# gateway MCP server (`python -m danus.gateway` via bin/danus-mcp). This script
# deliberately does NOT wire MCP itself; it only launches `codex` in the right
# directory. The strategic judgment (elaborate -> consult -> record
# master_guidance -> dispatch) lives in that main agent and its skills, not here.
#
#   bash examples/ops/main-agent-tmux.sh
#   tmux attach -t danus-main     # to watch / interact
#
# Requires: tmux, and the `codex` CLI on PATH (bin/codex is on PATH via env.sh).
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../../scripts/env.sh"

SESSION="${DANUS_MAIN_TMUX:-danus-main}"
MAIN_MODEL="${DANUS_MAIN_MODEL:-${DANUS_CODEX_MODEL:-gpt-5.6-sol}}"
MAIN_EFFORT="${DANUS_MAIN_EFFORT:-${DANUS_CODEX_EFFORT:-xhigh}}"

command -v tmux  >/dev/null 2>&1 || { echo "need tmux on PATH"   >&2; exit 1; }
command -v codex >/dev/null 2>&1 || { echo "need the codex CLI on PATH" >&2; exit 1; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[$SESSION] already running — attach with: tmux attach -t $SESSION"
  exit 0
fi

# Start codex detached in the repo root so it picks up AGENTS.md,
# .codex/config.toml, and .agents/skills. This is the intended autonomous mode;
# run it only on an isolated, disposable host (see docs/security-and-trust.md).
printf -v CODEX_CMD 'codex --model %q --config %q --dangerously-bypass-approvals-and-sandbox' \
  "$MAIN_MODEL" "model_reasoning_effort=\"$MAIN_EFFORT\""

# A long-lived tmux server keeps the environment from the moment that server was
# created. On this host, Codex network traffic must use the current Mihomo proxy;
# pass proxy variables into this session explicitly instead of trusting the stale
# tmux-server environment. Repeated `-e` is session-local and does not modify
# other tmux sessions.
TMUX_ENV_ARGS=()
for PROXY_NAME in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY \
                  http_proxy https_proxy all_proxy no_proxy; do
  PROXY_VALUE="${!PROXY_NAME:-}"
  if [ -n "$PROXY_VALUE" ]; then
    TMUX_ENV_ARGS+=( -e "$PROXY_NAME=$PROXY_VALUE" )
  fi
done

tmux new-session -d -s "$SESSION" -c "$DANUS_ROOT" \
  "${TMUX_ENV_ARGS[@]}" "$CODEX_CMD"
echo "[$SESSION] started in $DANUS_ROOT (model=$MAIN_MODEL effort=$MAIN_EFFORT) — attach with: tmux attach -t $SESSION"
