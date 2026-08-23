#!/usr/bin/env bash
# =============================================================================
# EXAMPLE, NOT CORE. Copy-pasteable demonstration of running Danus unattended.
# Nothing in the engine depends on examples/. See examples/README.md.
# =============================================================================
# main-agent-tmux.sh — run codex as a resident main agent inside tmux.
#
# This is the ONLY unattended mode in Danus: a long-lived codex session in the
# repo root. Because it starts in DANUS_ROOT it inherits the repo's AGENTS.md, its
# skills (.agents/skills), and .codex/config.toml — and .codex/config.toml is what
# wires the gateway MCP server (`python -m danus.gateway` via bin/danus-mcp). This
# script deliberately does NOT wire MCP itself; it only launches `codex` in the
# right directory. The strategic judgment (synthesize progress -> record
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

command -v tmux  >/dev/null 2>&1 || { echo "need tmux on PATH"   >&2; exit 1; }
command -v codex >/dev/null 2>&1 || { echo "need the codex CLI on PATH" >&2; exit 1; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[$SESSION] already running — attach with: tmux attach -t $SESSION"
  exit 0
fi

# Start codex detached, in the repo root, so it picks up AGENTS.md / .codex/config.toml /
# .agents/skills. --dangerously-bypass-approvals-and-sandbox = the intended autonomous mode
# (see README/security-and-trust.md); run only on an isolated, disposable host.
tmux new-session -d -s "$SESSION" -c "$DANUS_ROOT" "codex --dangerously-bypass-approvals-and-sandbox"
echo "[$SESSION] started in $DANUS_ROOT — attach with: tmux attach -t $SESSION"
