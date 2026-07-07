#!/usr/bin/env bash
# =============================================================================
# EXAMPLE, NOT CORE. Copy-pasteable demonstration of running Danus unattended.
# Nothing in the engine depends on examples/. See examples/README.md.
# =============================================================================
# watchdog.sh <project> — liveness / stall alerting via a generic notify hook.
#
# Periodically asks orchestration for the project's worker status (the public
# `danus status --json` verb, which already computes zombie-aware liveness + a
# `stuck?`/`dead`/`error` label — we reuse it rather than re-doing /proc logic)
# and probes that the verify service is up (no verify => fact_submit fails and
# the pipeline is silently dead). On any alarm it fires ${DANUS_NOTIFY:-:} with
# a message string. DANUS_NOTIFY is any command the operator sets (echo to a
# log, curl a webhook, ...); the default `:` is a silent no-op. There is no
# Telegram / vendor binding here.
#
#   bash examples/ops/watchdog.sh <project>
#   DANUS_NOTIFY='curl -fsS -d @- https://example/hook' bash examples/ops/watchdog.sh <project>
#
# Env:
#   DANUS_WATCHDOG_BEAT   seconds between checks (default 300)
#   DANUS_NOTIFY          alarm command; receives the message on argv + stdin
#   DANUS_VERIFY_URL      verify health endpoint (from env.sh; do not hardcode)
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../../scripts/env.sh"

PROJECT="${1:?usage: watchdog.sh <project>}"
BEAT="${DANUS_WATCHDOG_BEAT:-300}"
NOTIFY="${DANUS_NOTIFY:-:}"

_alarm(){ # <message>
  echo "[watchdog] ALARM: $1" >&2
  printf '%s\n' "$1" | $NOTIFY "$1" || true
}

echo "[watchdog] $PROJECT — beat ${BEAT}s, verify $DANUS_VERIFY_URL"

while :; do
  # 1) verify service up? (health probe against the env URL, not a hardcoded port)
  if ! curl -fsS --max-time 10 "${DANUS_VERIFY_URL%/verify}/health" >/dev/null 2>&1; then
    _alarm "verify service unreachable at $DANUS_VERIFY_URL — fact_submit will fail"
  fi

  # 2) any worker stuck / dead / errored? Parse the documented status JSON
  #    (fields: worker, state, round, age_s, label) with DANUS_PY (no jq dep).
  if STATUS="$(danus status "$PROJECT" --json 2>/dev/null)"; then
    BAD="$(printf '%s' "$STATUS" | "$DANUS_PY" -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for r in rows:
    if r.get("label") in ("stuck?", "dead", "error"):
        print("%s: label=%s state=%s round=%s age_s=%s"
              % (r.get("worker"), r.get("label"), r.get("state"),
                 r.get("round"), r.get("age_s")))
')"
    if [ -n "$BAD" ]; then
      _alarm "worker(s) unhealthy on $PROJECT:"$'\n'"$BAD"
    fi
  else
    _alarm "could not read status for project $PROJECT (danus status failed)"
  fi

  sleep "$BEAT"
done
