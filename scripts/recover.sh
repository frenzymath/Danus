#!/usr/bin/env bash
# =============================================================================
# recover.sh — bring Danus back after a host restart, near-losslessly.
#
#   bash scripts/recover.sh
#
# All Danus memory/state lives under this repo (+ runtime/): every project's fact
# graph + global memory and OPERATOR.md. Native Codex authentication lives in the
# Codex profile and is checked, not rebuilt, here. Recovery (1) rebuilds the
# toolchain (notably the venv, whose base interpreter can go dangling if the host
# python moved) and (2) restarts the services that were running. Idempotent; safe
# to run anytime.
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"

echo "== [1/4] rebuild toolchain (bootstrap: validates/recreates the venv and codex runtime) =="
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
bash "$HERE/check-codex.sh" 2>/dev/null | sed 's/^/  codex: /' || true
bash "$HERE/services.sh" status
echo "done — recovery complete."
