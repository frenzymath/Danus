#!/usr/bin/env bash
# =============================================================================
# recover.sh — bring Danus back after a host restart, near-losslessly.
#
#   bash scripts/recover.sh
#
# All memory/state lives under this repo (+ runtime/): codex auth, every
# project's fact graph + global memory, OPERATOR.md. Recovery only (1) rebuilds
# the toolchain (notably the venv, whose base interpreter can go dangling if the
# host python moved) and (2) restarts the services that were running. Idempotent;
# safe to run anytime.
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"

echo "== [1/4] rebuild toolchain (bootstrap: validates/recreates the venv, codex provider) =="
bash "$HERE/bootstrap.sh" || { echo "recover: bootstrap failed — fix that first"; exit 1; }

echo "== [2/4] clear stale pidfiles (the processes died with the host) =="
rm -f "$DANUS_RUNTIME/run/"*.pid 2>/dev/null || true

echo "== [3/4] restart the services that were running =="
AUTO="$DANUS_RUNTIME/run/autostart"
if [ -s "$AUTO" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    echo "  -> services.sh up $line"
    bash "$HERE/services.sh" up $line || true
  done < "$AUTO"
else
  echo "  (no autostart manifest — nothing was recorded as running)"
  echo "  the verify service is required before workers can submit facts:"
  echo "     bash scripts/services.sh up verify"
fi

echo "== [4/4] health =="
if [ "${CODEX_BACKEND:-api}" = "api" ]; then
  bash "$HERE/check-codex.sh" 2>/dev/null | sed 's/^/  codex: /' || true
else
  env CODEX_HOME="$CODEX_HOME" "$DANUS_ROOT/bin/codex" login status >/dev/null 2>&1 \
    && echo "  codex: login ok (chatgpt, $CODEX_HOME)" \
    || echo "  codex: NOT logged in (scripts/setup-codex.sh login)"
fi
bash "$HERE/services.sh" status
echo "done — recovery complete."
