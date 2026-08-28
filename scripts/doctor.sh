#!/usr/bin/env bash
# Health check: config, runtime, python deps, codex, verify service. Read-only.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../scripts/env.sh"
ok(){ printf '  \033[32mok\033[0m   %s\n' "$1"; }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
wn(){ printf '  \033[33mwarn\033[0m %s\n' "$1"; }
echo "== Danus doctor =="
echo "DANUS_ROOT=$DANUS_ROOT"
[ -f "$DANUS_ROOT/config/danus.env" ] && ok "config/danus.env present" || wn "config/danus.env missing (copy from .example)"
[ -n "${DANUS_PY:-}" ] && [ -x "$DANUS_PY" ] && ok "python: $DANUS_PY" || no "no python (run bootstrap.sh)"
"$DANUS_PY" -c 'from danus._mcp import FastMCP' 2>/dev/null && ok "python dep: mcp" || no "python dep: mcp missing or incompatible"
(cd / && "$DANUS_PY" -c 'import danus' 2>/dev/null) && ok "python pkg: danus (importable from any cwd)" || no "danus package not installed in the venv — worker MCP gateway and bin/ wrappers fail off the repo root (run bootstrap.sh)"
"$DANUS_PY" -c 'import fastapi, uvicorn, pydantic' 2>/dev/null && ok "python deps: fastapi/uvicorn/pydantic" || no "verify-service deps missing"
if [ -n "${DANUS_NODE:-}" ] && [ -x "${DANUS_NODE:-/nonexist}" ]; then ok "node: $DANUS_NODE"; else wn "node not provisioned"; fi
if "$DANUS_ROOT/bin/codex" --version >/dev/null 2>&1; then ok "codex: $("$DANUS_ROOT/bin/codex" --version 2>/dev/null)"; else no "codex wrapper not working (run bootstrap.sh)"; fi
bash "$DANUS_ROOT/scripts/check-codex.sh" >/dev/null 2>&1 && ok "codex native authentication configured" || wn "codex authentication missing (bin/codex login --device-auth or set CODEX_API_KEY)"
case "$(danus_verify_health)" in
  ours)    ok "verify service up :$VERIFY_PORT (ours)" ;;
  foreign) no "verify port :$VERIFY_PORT answered by a FOREIGN process — another deployment holds this port; set a distinct VERIFY_PORT/DASHBOARD_PORT in config/danus.env (fact_submit would post to the wrong verifier)" ;;
  stale)   wn "verify service down :$VERIFY_PORT (stale pidfile; scripts/services.sh up verify)" ;;
  *)       wn "verify service down :$VERIFY_PORT (scripts/services.sh up verify)" ;;
esac
# write-paper PDF render (soft): TEX_ENGINE override, else pdflatex on PATH.
TEX="${TEX_ENGINE:-pdflatex}"
command -v "$TEX" >/dev/null 2>&1 && ok "latex: $TEX ($($TEX --version 2>/dev/null | head -1))" || wn "no $TEX on PATH (write-paper PDF render needs it; set TEX_ENGINE or install TeX)"
# human-summary PDF render (soft): DANUS_CHROME_BIN, else chrome/chromium on PATH.
CHROME="${DANUS_CHROME_BIN:-}"; [ -z "$CHROME" ] && CHROME="$(command -v chromium chromium-browser google-chrome google-chrome-stable 2>/dev/null | head -1)"
{ [ -n "$CHROME" ] && [ -x "$CHROME" ]; } && ok "chrome: $CHROME (human-summary PDF)" || wn "no Chrome/Chromium (human-summary PDF render needs it; set DANUS_CHROME_BIN or install)"
echo "done."
