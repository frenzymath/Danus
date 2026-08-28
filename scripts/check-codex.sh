#!/usr/bin/env bash
# =============================================================================
# check-codex.sh — check native Codex authentication and leave a trace.
#
# Checks Codex's native authentication state, then scans recent worker + verify
# logs for request failures. Appends a JSON line to
# runtime/logs/codex-health.jsonl each time. Exit 0 if authentication is
# configured, 1 if not.
#
#   bash scripts/check-codex.sh           # auth check + scan + append trace
#   tail runtime/logs/codex-health.jsonl  # the call history
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../scripts/env.sh"
LOG="$DANUS_RUNTIME/logs"; mkdir -p "$LOG"
TRACE="$LOG/codex-health.jsonl"
TS="$(date -u +%FT%TZ)"

DANUS_CODEX_BIN="${DANUS_CODEX_BIN:-$DANUS_ROOT/bin/codex}"
if [ -n "${CODEX_API_KEY:-}" ]; then
  auth_ok=true
  auth_kind=api-key
  auth_detail="CODEX_API_KEY configured"
elif LOGIN_OUT="$("$DANUS_CODEX_BIN" login status 2>&1)"; then
  auth_ok=true
  auth_kind=stored-login
  auth_detail="$(printf '%s\n' "$LOGIN_OUT" | tail -1)"
else
  auth_ok=false
  auth_kind=none
  auth_detail="$(printf '%s\n' "$LOGIN_OUT" | tail -1)"
fi
echo "{\"ts\":\"$TS\",\"kind\":\"auth-status\",\"auth\":\"$auth_kind\",\"ok\":$auth_ok}" >> "$TRACE"

# --- (b) scan recent worker + verify logs for API-failure signatures ---
SIG='error sending request|stream disconnected|unexpected status|status 429|status 5[0-9][0-9]|rate limit|Too Many Requests|Unauthorized|quota|timed out|request failed'
recent_fail=0
while IFS= read -r f; do
  grep -qiE "$SIG" "$f" 2>/dev/null && recent_fail=$((recent_fail+1))
done < <(ls -t "$DANUS_AGENTS_ROOT"/*/workers/*/logs/round_*.log \
                "$VERIFIER_RESULTS_DIR"/*/log.md 2>/dev/null | head -30)

echo "{\"ts\":\"$TS\",\"kind\":\"scan\",\"recent_logs_with_api_errors\":$recent_fail}" >> "$TRACE"

# --- report ---
if [ "$auth_ok" = true ]; then
  echo "ok   codex native authentication active ($auth_detail)"
  [ "$recent_fail" -gt 0 ] && echo "warn $recent_fail recent worker/verify log(s) show API errors — inspect runtime/logs + verify-runs"
  exit 0
fi
echo "FAIL codex authentication is not configured: $auth_detail"
echo "  run: $DANUS_CODEX_BIN login --device-auth"
exit 1
