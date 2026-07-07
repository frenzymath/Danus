#!/usr/bin/env bash
# Configure the codex backend used by the workers + the verifier.
#
#   bash scripts/setup-codex.sh api      # use your BYO OpenAI-compatible endpoint
#                                        # from config/codex.env — no login needed
#   bash scripts/setup-codex.sh login    # alternative: device-auth YOUR ChatGPT account
#   bash scripts/setup-codex.sh status   # show the active backend + a live ping
#
# `api` writes a model_provider into $CODEX_HOME/config.toml pointing at the
# OpenAI-compatible endpoint; the key is read at run time from the env var named
# by `env_key` (DANUS_CODEX_API_KEY, exported by env.sh from config/codex.env).
# $CODEX_HOME is under runtime/ (gitignored) and rebuilt by bootstrap.sh.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../scripts/env.sh"
mkdir -p "$CODEX_HOME"
export DANUS_CODEX_BIN="${DANUS_CODEX_BIN:-$DANUS_ROOT/bin/codex}"
export PATH="$(dirname "$DANUS_CODEX_BIN"):$PATH"

write_provider(){
  : "${CODEX_API_BASE_URL:?CODEX_API_BASE_URL not set (config/codex.env)}"
  : "${DANUS_CODEX_API_KEY:?DANUS_CODEX_API_KEY not set (config/codex.env)}"
  cat > "$CODEX_HOME/config.toml" <<EOF
# Auto-written by scripts/setup-codex.sh api — codex model backend for Danus.
# The API key is read at run time from the env var below (env.sh exports it from
# config/codex.env); it is NOT stored in this file.
model_provider = "danus_api"

[model_providers.danus_api]
name = "Danus codex API (${CODEX_API_MODEL:-gpt-5.5})"
base_url = "$CODEX_API_BASE_URL"
env_key = "DANUS_CODEX_API_KEY"
wire_api = "responses"
EOF
  echo "[setup-codex] wrote $CODEX_HOME/config.toml (provider danus_api -> $CODEX_API_BASE_URL, model ${CODEX_API_MODEL:-gpt-5.5})"
}

case "${1:-status}" in
  api)
    write_provider
    echo "[setup-codex] backend = api. Verify with: bash scripts/check-codex.sh"
    ;;
  login|apikey)
    # ChatGPT-subscription path: remove the API provider so codex uses its own
    # auth, then run codex's own device-auth login flow.
    [ -f "$CODEX_HOME/config.toml" ] && grep -q 'model_provider = "danus_api"' "$CODEX_HOME/config.toml" 2>/dev/null \
      && { rm -f "$CODEX_HOME/config.toml"; echo "[setup-codex] removed the api provider (switching to ChatGPT login)"; }
    echo "[setup-codex] launching codex login (device auth) — CODEX_HOME=$CODEX_HOME"
    # --device-auth: the code-entry flow that works on a headless server. The
    # default `codex login` flow needs a browser reaching localhost:1455 and
    # just hangs silently over plain ssh.
    exec env CODEX_HOME="$CODEX_HOME" "$DANUS_CODEX_BIN" login --device-auth
    ;;
  status)
    echo "[setup-codex] CODEX_BACKEND=$CODEX_BACKEND  CODEX_HOME=$CODEX_HOME"
    if [ -f "$CODEX_HOME/config.toml" ] && grep -q danus_api "$CODEX_HOME/config.toml"; then
      echo "  provider: danus_api ($CODEX_API_BASE_URL, ${CODEX_API_MODEL:-gpt-5.5})"
    else
      echo "  provider: codex default (ChatGPT login) — $(env CODEX_HOME="$CODEX_HOME" "$DANUS_CODEX_BIN" login status 2>&1 | head -1)"
    fi
    ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
