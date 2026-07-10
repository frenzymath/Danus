#!/usr/bin/env bash
# =============================================================================
# EXAMPLE, NOT CORE. Copy-pasteable demonstration of running Danus unattended.
# Nothing in the engine depends on examples/. See examples/README.md.
# =============================================================================
# strategy-loop.sh <project> — the ONE parameterized strategic-cadence loop.
#
# Mechanizes the CADENCE of a strategic consult, nothing more. Each beat it
# calls the consult CLI (bin/consult) on the project's current elaboration and
# writes the reply to a file. It deliberately does NOT record master_guidance
# or dispatch workers: the elaborate -> consult -> record-master_guidance
# -> dispatch chain is owned by the resident Claude-Code main agent and its
# `elaboration` / `consult` skills (recording is a gm_add through the
# gateway, which keeps the global-memory kinds + role gating intact). This shell
# only provides the unattended timing + the raw consult call around that.
#
# Consult on NEW STATE, not a blind timer — a real deployment lets the main
# agent decide when to consult (a worker finished a round, a new dead end, the
# swarm is stuck). This loop is a simple fixed-beat stand-in for that cadence.
#
#   bash examples/ops/strategy-loop.sh <project>
#   touch runtime/projects/<project>/.strategy.stop   # graceful stop (at next beat)
#
# Env:
#   DANUS_STRATEGY_BEAT   seconds between consults (default 7200 = ~2h; the
#                         skill's guidance is at most once every ~2h)
#   DANUS_CONSULT_TRANSPORT   gpt_pro | claude_api | claude_code | off (default gpt_pro)
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../../scripts/env.sh"

PROJECT="${1:?usage: strategy-loop.sh <project>}"
PROJDIR="$DANUS_AGENTS_ROOT/$PROJECT"
[ -d "$PROJDIR" ] || { echo "no such project: $PROJDIR" >&2; exit 1; }

BEAT="${DANUS_STRATEGY_BEAT:-7200}"
TRANSPORT="${DANUS_CONSULT_TRANSPORT:-gpt_pro}"
STOP="$PROJDIR/.strategy.stop"
OUTDIR="$PROJDIR/strategy"; mkdir -p "$OUTDIR"

echo "[strategy-loop] $PROJECT — beat ${BEAT}s, transport $TRANSPORT (stop: touch $STOP)"

while :; do
  if [ -f "$STOP" ]; then
    rm -f "$STOP"
    echo "[strategy-loop] .strategy.stop seen — exiting gracefully"
    break
  fi

  # The elaboration is the consult prompt. The main agent's `elaboration` skill
  # publishes it (gm_add kind=elaboration) and can also drop a copy here; if none
  # exists yet we skip this beat rather than consult on nothing.
  ELAB="$PROJDIR/strategy/elaboration.md"
  if [ -s "$ELAB" ]; then
    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    REPLY="$OUTDIR/reply-$STAMP.md"
    echo "[strategy-loop] consult ($TRANSPORT) -> $REPLY"
    # Uses the `consult` CLI (bin/consult -> python -m danus.strategy).
    consult --file "$ELAB" --project "$PROJDIR" --out "$REPLY" \
            --transport "$TRANSPORT" || echo "[strategy-loop] consult failed (continuing)"
    # NOTE: a real deployment records this reply as master_guidance via the
    # gateway (the consult skill's gm_add) and dispatches workers from it.
    # We do NOT write the store from shell — that write is owned by the skill.
  else
    echo "[strategy-loop] no elaboration at $ELAB yet — skipping this beat"
  fi

  sleep "$BEAT"
done
