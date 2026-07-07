#!/usr/bin/env bash
# Start the Danus verify service (resident HTTP gateway on 127.0.0.1:$VERIFY_PORT;
# each POST /verify spawns a fresh codex verify agent). Run via services.sh so it
# outlives the launching shell:  bash scripts/services.sh up verify
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../scripts/env.sh"
mkdir -p "$DANUS_RUNTIME/logs" "$VERIFIER_RESULTS_DIR"
export DANUS_CODEX_BIN="${DANUS_CODEX_BIN:-$DANUS_ROOT/bin/codex}"   # the provisioned codex wrapper
export CODEX_HOME
export CODEX_TIMEOUT_SECONDS="${CODEX_TIMEOUT_SECONDS:-900}"
export VERIFY_HOST="${VERIFY_HOST:-127.0.0.1}" VERIFY_PORT
echo "[start-verify] port=$VERIFY_PORT model=${DANUS_VERIFY_MODEL:-$DANUS_CODEX_MODEL}/${DANUS_VERIFY_EFFORT:-$DANUS_CODEX_EFFORT} CODEX_HOME=$CODEX_HOME"
exec "$DANUS_PY" -m danus.verify
