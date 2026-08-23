#!/usr/bin/env bash
# doctor.sh — soft health check for the human-summary render pipeline.
# Read-only; never fails hard. Reports whether the PDF-render prerequisites are
# present: node, a headless Chrome/Chromium binary, and the vendored KaTeX CSS.
#
# The render dep is a headless Chrome BINARY for --print-to-pdf — it is only used
# locally to snapshot KaTeX-rendered HTML to PDF. The ops layer (scripts/env.sh +
# scripts/doctor.sh) should export/soft-check DANUS_CHROME_BIN alongside this skill.
#
#   bash doctor.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/../../../scripts/env.sh" >/dev/null 2>&1 || true
ok()   { printf '  [ok]   %s\n' "$1"; }
warn() { printf '  [WARN] %s\n' "$1"; }

echo "human-summary render prerequisites:"

if command -v node >/dev/null 2>&1; then ok "node: $(node --version 2>/dev/null)"
else warn "node not found — run scripts/bootstrap.sh"; fi

CHROME="${DANUS_CHROME_BIN:-google-chrome}"
if command -v "$CHROME" >/dev/null 2>&1; then ok "chrome: $CHROME"
else warn "no Chrome binary ('$CHROME') — set DANUS_CHROME_BIN or install Chrome/Chromium (PDF render needs it)"; fi

if [ -d "$HERE/node_modules/katex" ]; then ok "katex node module present (offline CSS)"
else warn "katex not installed yet — render_pdf.sh installs it on first run (needs one-time network)"; fi

exit 0
