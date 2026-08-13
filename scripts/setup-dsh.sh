#!/usr/bin/env bash
# =============================================================================
# Danus dsh provisioning — install the DeepSeek Harness CLI under runtime/.
#
#   bash scripts/setup-dsh.sh
#
# Idempotent: re-running skips an existing install. Installs @deepseek-ai/dsh
# into runtime/tools/dsh (gitignored) and writes the machine paths
# (DANUS_DSH_NODE / DANUS_DSH_BIN) into runtime/runtime.env, merging with any
# lines bootstrap.sh wrote (only the DANUS_DSH_* lines are replaced).
#
# This is the prerequisite for CODEX_BACKEND=dsh (bin/codex-dsh) and the
# `dsh` consult transport; the actual DeepSeek credentials + default model are
# the deployment DSH home's (${DANUS_DSH_HOME:-$HOME/.dsh}, the same home the
# `dsh web` GUI uses).
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DANUS_ROOT="$(cd "$HERE/.." && pwd)"
RT="$DANUS_ROOT/runtime"
DSH_VERSION="${DSH_VERSION:-^0.1.0-rc.6}"
mkdir -p "$RT/logs"
log(){ printf '[setup-dsh] %s\n' "$*"; }

# Be polite about IO/CPU (do not saturate a shared host).
NICE="nice -n19"; command -v ionice >/dev/null 2>&1 && NICE="ionice -c3 $NICE"

# node: dsh requires Node >= 24 (node:zlib's zstd API). Prefer the system node
# when it qualifies, then the bootstrap node, else fail loud — a DANUS_DSH_NODE
# override in the environment always wins.
node_ok() { [ -x "$1" ] && [ "$( "$1" --version 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/' )" -ge 24 ]; }
DSH_NODE=""
if [ -n "${DANUS_DSH_NODE:-}" ] && node_ok "${DANUS_DSH_NODE}"; then
  DSH_NODE="$DANUS_DSH_NODE"
elif node_ok "$(command -v node 2>/dev/null)"; then
  DSH_NODE="$(command -v node)"
elif node_ok "$RT/node22/bin/node"; then
  DSH_NODE="$RT/node22/bin/node"
else
  log "FATAL: no node >= 24 on PATH (dsh needs node:zlib zstd); install node 24+ or set DANUS_DSH_NODE"
  exit 1
fi
log "using node for dsh: $DSH_NODE ($("$DSH_NODE" --version))"

DSH_NPM="$RT/tools/dsh"
DSH_JS="$(find "$DSH_NPM" -path '*/@deepseek-ai/dsh/lib/bin.js' 2>/dev/null | head -1 || true)"
if [ -n "$DSH_JS" ]; then
  log "dsh present: $DSH_JS"
else
  log "installing @deepseek-ai/dsh@$DSH_VERSION -> $DSH_NPM"
  mkdir -p "$DSH_NPM"
  # Custom cache: the platform's default npm cache dir may be read-only.
  $NICE npm install --prefix "$DSH_NPM" --cache "$RT/npm-cache" \
    --no-audit --no-fund --no-package-lock "@deepseek-ai/dsh@$DSH_VERSION" >/dev/null 2>&1 \
    || { log "FATAL: npm install @deepseek-ai/dsh failed"; exit 1; }
  DSH_JS="$(find "$DSH_NPM" -path '*/@deepseek-ai/dsh/lib/bin.js' 2>/dev/null | head -1 || true)"
  [ -n "$DSH_JS" ] || { log "FATAL: dsh bin.js not found after install"; exit 1; }
fi

# --- write the machine paths into runtime/runtime.env (merge, don't clobber) --
ENVF="$RT/runtime.env"
{ [ -f "$ENVF" ] && grep -v '^export DANUS_DSH_' "$ENVF" || true; } > "$ENVF.tmp"
cat >> "$ENVF.tmp" <<ENV
# Written by scripts/setup-dsh.sh — machine paths for the dsh backend/transport.
export DANUS_DSH_NODE=$DSH_NODE
export DANUS_DSH_BIN=$DSH_JS
ENV
mv "$ENVF.tmp" "$ENVF"
log "wrote $ENVF"

log "done. The dsh backend is selected with CODEX_BACKEND=dsh (config/danus.env);"
log "  the consult transport with DANUS_CONSULT_TRANSPORT=dsh. Credentials and"
log "  default model come from ${DANUS_DSH_HOME:-$HOME/.dsh} (the dsh web home)."
