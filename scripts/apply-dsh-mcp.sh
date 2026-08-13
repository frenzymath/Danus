#!/usr/bin/env bash
# =============================================================================
# Danus x dsh — register the danus / write-paper / human-summary MCPs in a dsh
# profile (default: the web profile). ONE command; it backs up, writes,
# validates the composed profile, and handshake-probes every MCP server.
#
#   bash scripts/apply-dsh-mcp.sh [profile]     # profile defaults to web
#
# Steps:
#   1. backs up <home>/profiles/<profile>/cordis.patch.yml (timestamped)
#   2. writes the three mcp-client rows — generated from
#      examples/dsh-integration/cordis.patch.yml.example with <repo>
#      substituted by THIS repo's path
#   3. validates the composed profile: dsh --profile <profile> --dump-config
#   4. handshake-probes each MCP server (scripts/dsh_mcp_probe.py, the venv
#      python), so a green run means the rows will load in the dsh session
#
# The dsh <profile> server must be RESTARTED afterwards (this script never
# touches a running server); new sessions then see the mcp__danus__* /
# mcp__write-paper__* / mcp__human-summary__* tools.
#
# The profile dir is resolved from \$DSH_HOME (default ~/.dsh) — an env
# override makes the whole script testable against a scratch home.
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DANUS_ROOT="$(cd "$HERE/.." && pwd)"
. "$DANUS_ROOT/scripts/env.sh" >/dev/null 2>&1 || true

PROFILE="${1:-web}"
HOME_DIR="${DSH_HOME:-$HOME/.dsh}"
PROF_DIR="$HOME_DIR/profiles/$PROFILE"
TPL="$DANUS_ROOT/examples/dsh-integration/cordis.patch.yml.example"

[ -d "$PROF_DIR" ] || { echo "[apply-dsh-mcp] FATAL: no profile dir $PROF_DIR (boot the $PROFILE profile once first)" >&2; exit 1; }
[ -f "$TPL" ] || { echo "[apply-dsh-mcp] FATAL: missing template $TPL" >&2; exit 1; }
if [ -z "${DANUS_DSH_BIN:-}" ] || [ ! -f "${DANUS_DSH_BIN}" ]; then
  echo "[apply-dsh-mcp] FATAL: dsh not provisioned — run scripts/setup-dsh.sh first" >&2
  exit 1
fi

# --- 1) backup ---------------------------------------------------------------
TS="$(date -u +%Y%m%dT%H%M%SZ)"
if [ -f "$PROF_DIR/cordis.patch.yml" ]; then
  cp "$PROF_DIR/cordis.patch.yml" "$PROF_DIR/cordis.patch.yml.bak-$TS"
  echo "[apply-dsh-mcp] backup: $PROF_DIR/cordis.patch.yml.bak-$TS"
fi

# --- 2) write the rows (template with <repo> substituted) ---------------------
sed "s|<repo>|$DANUS_ROOT|g" "$TPL" > "$PROF_DIR/cordis.patch.yml"
echo "[apply-dsh-mcp] wrote $PROF_DIR/cordis.patch.yml"

# --- 3) validate the composed profile ------------------------------------------
if env DSH_HOME="$HOME_DIR" "${DANUS_DSH_NODE:-node}" "$DANUS_DSH_BIN" \
     --profile "$PROFILE" --dump-config >/dev/null 2>"$DANUS_ROOT/runtime/logs/apply-dsh-mcp-dump.log"; then
  echo "[apply-dsh-mcp] profile composition OK"
else
  echo "[apply-dsh-mcp] FATAL: dump-config failed — see runtime/logs/apply-dsh-mcp-dump.log" >&2
  exit 1
fi

# --- 4) handshake-probe the three MCP servers ----------------------------------
"${DANUS_PY:-python3}" "$DANUS_ROOT/scripts/dsh_mcp_probe.py" "$DANUS_ROOT" main \
  || { echo "[apply-dsh-mcp] FATAL: MCP probe failed — the rows would not load" >&2; exit 1; }

echo "[apply-dsh-mcp] done. Restart the dsh $PROFILE server to load the tools."
