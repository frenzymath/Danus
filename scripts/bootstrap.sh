#!/usr/bin/env bash
# =============================================================================
# Danus bootstrap — provision the self-contained runtime under runtime/.
#
#   bash scripts/bootstrap.sh
#
# Idempotent: re-running skips anything already in place. Installs into
# runtime/ (gitignored), so the deployment tree stays clean and the whole
# toolchain is self-contained (no system-wide installs). Provisions:
#   1) Node 22            -> runtime/node22            (official tarball)
#   2) Python venv + deps -> runtime/venv             (mcp/fastapi/uvicorn/pydantic/openai/anthropic
#                                                      + the danus package itself, editable)
#   3) codex CLI          -> runtime/codex-npm        (npm @openai/codex)
#   4) node skill deps    -> human-summary/node_modules (markdown-it/katex, soft)
#   5) writes runtime/runtime.env (machine paths read by scripts/env.sh)
#   6) if config/codex.env holds a real BYO key, writes the codex model_provider
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DANUS_ROOT="$(cd "$HERE/.." && pwd)"
RT="$DANUS_ROOT/runtime"
NODE_VERSION="${NODE_VERSION:-v22.14.0}"
ARCH="$(uname -m)"; case "$ARCH" in x86_64) NARCH=x64;; aarch64|arm64) NARCH=arm64;; *) NARCH=x64;; esac
mkdir -p "$RT/logs"
log(){ printf '[bootstrap] %s\n' "$*"; }

# Be polite about IO/CPU (do not saturate a shared host).
NICE="nice -n19"; command -v ionice >/dev/null 2>&1 && NICE="ionice -c3 $NICE"

# --- 1) Node 22 -------------------------------------------------------------
NODE_DIR="$RT/node22"
if [ -x "$NODE_DIR/bin/node" ]; then
  log "node present: $("$NODE_DIR/bin/node" --version)"
else
  log "installing Node $NODE_VERSION ($NARCH) -> $NODE_DIR"
  TARBALL="node-$NODE_VERSION-linux-$NARCH.tar.xz"
  $NICE curl -fsSL "https://nodejs.org/dist/$NODE_VERSION/$TARBALL" -o "$RT/$TARBALL" || true
  [ -s "$RT/$TARBALL" ] || { log "FATAL: could not download node (set NODE_VERSION / check network)"; exit 1; }
  mkdir -p "$NODE_DIR"
  tar -xJf "$RT/$TARBALL" -C "$NODE_DIR" --strip-components=1
  rm -f "$RT/$TARBALL"
  log "node installed: $("$NODE_DIR/bin/node" --version)"
fi
export PATH="$NODE_DIR/bin:$PATH"

# --- 2) Python venv + deps --------------------------------------------------
# A venv's base interpreter is referenced by absolute path (pyvenv.cfg `home`).
# If that base interpreter ever moves or is removed, the venv can't run even
# though its site-packages survive. So VALIDATE that the venv actually executes
# + imports the deps, and REBUILD it from a fresh base python if not.
VENV="$RT/venv"
export PIP_DISABLE_PIP_VERSION_CHECK=1
DEPS='import mcp,fastapi,uvicorn,pydantic,openai,anthropic'
if "$VENV/bin/python" -c "$DEPS" 2>/dev/null; then
  log "venv present + healthy"
else
  [ -e "$VENV" ] && { log "venv missing/broken (dangling base interpreter?) — rebuilding"; rm -rf "$VENV"; }
  PYBASE="$(command -v python3)"; [ -n "$PYBASE" ] || { log "FATAL: no python3 on PATH to build the venv"; exit 1; }
  log "creating venv ($PYBASE) -> $VENV"
  "$PYBASE" -m venv "$VENV"
  log "installing python deps (mcp/fastapi/uvicorn/pydantic/openai/anthropic)"
  $NICE "$VENV/bin/pip" install --quiet --no-cache-dir --upgrade pip >/dev/null 2>&1 || true
  $NICE "$VENV/bin/pip" install --quiet --no-cache-dir \
    "mcp>=1.0.0" "fastapi>=0.110.0" "uvicorn>=0.30.0" "pydantic>=2.0" "openai>=2.40" \
    "anthropic>=0.92" \
    || { log "FATAL: pip install failed"; exit 1; }
  "$VENV/bin/python" -c "$DEPS" || { log "FATAL: venv still missing deps after install"; exit 1; }
fi

# --- 2b) the danus package itself (editable install) ------------------------
# Workers' MCP gateway, the verify service, and the bin/ wrappers all run
# `python -m danus.*` from arbitrary cwds (worker dirs, codex sessions), so the
# package must live on the venv's sys.path — cwd-on-sys.path only helps at the
# repo root. Editable, so a `git pull` needs no re-install. Validate from a
# neutral cwd: at the repo root a missing install is masked (cwd is sys.path[0]).
if (cd / && "$VENV/bin/python" -c 'import danus' 2>/dev/null); then
  log "danus package present in venv"
else
  log "installing the danus package (editable) into the venv"
  $NICE "$VENV/bin/pip" install --quiet --no-cache-dir -e "$DANUS_ROOT" \
    || { log "FATAL: pip install -e failed (the danus package)"; exit 1; }
  (cd / && "$VENV/bin/python" -c 'import danus') \
    || { log "FATAL: danus still not importable after editable install"; exit 1; }
fi

# --- 3) codex CLI (npm @openai/codex) --------------------------------------
# NB: `find … | head` can exit non-zero under `set -o pipefail` (find errors when
# the dir is absent) — `|| true` keeps that from tripping `set -e`.
CODEX_NPM="$RT/codex-npm"
CODEX_JS="$(find "$CODEX_NPM" -path '*/@openai/codex/bin/codex.js' 2>/dev/null | head -1 || true)"
if [ -n "$CODEX_JS" ]; then
  log "codex present: $CODEX_JS"
else
  log "installing @openai/codex -> $CODEX_NPM"
  mkdir -p "$CODEX_NPM"
  $NICE "$NODE_DIR/bin/npm" install -g --prefix "$CODEX_NPM" @openai/codex >/dev/null 2>&1 \
    || { log "FATAL: npm install @openai/codex failed"; exit 1; }
  CODEX_JS="$(find "$CODEX_NPM" -path '*/@openai/codex/bin/codex.js' 2>/dev/null | head -1 || true)"
  [ -n "$CODEX_JS" ] || { log "FATAL: codex.js not found after install"; exit 1; }
fi

# --- 4) node skill deps (human-summary: markdown-it + katex) ---------------
HS="$DANUS_ROOT/.claude/skills/human-summary"
if [ -d "$HS" ] && [ ! -d "$HS/node_modules/katex" ]; then
  log "installing human-summary node deps (markdown-it/katex)"
  ( cd "$HS" && $NICE "$NODE_DIR/bin/npm" install --no-fund --no-audit >/dev/null 2>&1 ) \
    || log "WARN: human-summary npm install failed (PDF render needs it)"
fi

# --- 5) write runtime/runtime.env (machine paths for scripts/env.sh) -------
cat > "$RT/runtime.env" <<ENV
# Auto-generated by scripts/bootstrap.sh — machine-derived paths. Do not edit by
# hand (re-run bootstrap). Sourced by scripts/env.sh after config/danus.env.
export DANUS_NODE=$NODE_DIR/bin/node
export DANUS_NODE_BIN=$NODE_DIR/bin
export DANUS_CODEX_JS=$CODEX_JS
export DANUS_VENV=$VENV
ENV
log "wrote $RT/runtime.env"

# --- 6) codex backend = your BYO API key (config/codex.env) ------------------
# Writes the model_provider into $CODEX_HOME/config.toml (no ChatGPT login).
# Guard: only if config/codex.env exists with a real (non-placeholder) key.
. "$DANUS_ROOT/scripts/env.sh" >/dev/null 2>&1 || true
if [ "${CODEX_BACKEND:-api}" = "api" ] \
   && [ -n "${DANUS_CODEX_API_KEY:-}" ] && [ -n "${CODEX_API_BASE_URL:-}" ] \
   && case "$DANUS_CODEX_API_KEY" in *"<"*|*"your"*) false;; *) true;; esac; then
  bash "$DANUS_ROOT/scripts/setup-codex.sh" api 2>&1 | sed 's/^/[bootstrap] /' \
    || log "WARN: could not write the codex api provider config"
else
  log "codex api provider NOT written — fill config/codex.env (cp config/codex.env.example)"
  log "  with your BYO endpoint + key, then re-run bootstrap (or: scripts/setup-codex.sh api)"
fi

log "done. Next:"
log "  1) cp config/danus.env.example config/danus.env   # and edit (optional)"
log "  2) cp config/codex.env.example config/codex.env    # fill BYO endpoint + key"
log "  3) bash scripts/check-codex.sh                     # confirm the codex API is reachable"
log "  4) bash scripts/doctor.sh                          # full health check"
