#!/usr/bin/env bash
# Render a markdown+LaTeX human report to a clean PDF:
#   markdown-it + KaTeX server-render -> self-contained HTML -> headless Chrome --print-to-pdf.
# Chrome handles the math (KaTeX) + fonts, so no LaTeX/TeX engine is needed here.
#
#   bash render_pdf.sh <report.md> <out.pdf> ["Title"]
#
# Prerequisites (see SKILL.md): a headless Chrome/Chromium binary (via
# DANUS_CHROME_BIN or a `google-chrome` on PATH) and node (provisioned by
# scripts/bootstrap.sh). The KaTeX CSS is vendored locally — no network at render.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
# Load node (provisioned by bootstrap) + DANUS_CHROME_BIN from the single deployment env chain.
. "$HERE/../../../scripts/env.sh" >/dev/null 2>&1 || true
IN="${1:?usage: render_pdf.sh <report.md> <out.pdf> [title]}"
OUT="${2:?need <out.pdf>}"; TITLE="${3:-}"
CHROME="${DANUS_CHROME_BIN:-google-chrome}"
command -v "$CHROME" >/dev/null 2>&1 || {
  echo "render_pdf: no Chrome binary ('$CHROME') — set DANUS_CHROME_BIN or install Chrome/Chromium; see SKILL.md" >&2
  exit 3
}
# Install node deps once (offline-friendly: only if the katex module is absent).
[ -d "$HERE/node_modules/katex" ] || (cd "$HERE" && npm install --no-fund --no-audit markdown-it katex >/dev/null 2>&1)
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
node "$HERE/md2html.js" "$IN" "$TMP/r.html" "$TITLE"
# --virtual-time-budget + --run-all-compositor-stages-before-draw: let KaTeX finish
# laying out before the PDF snapshot, else formulas can render half-drawn.
"$CHROME" --headless --disable-gpu --no-sandbox --print-to-pdf="$OUT" \
  --virtual-time-budget=25000 --run-all-compositor-stages-before-draw "file://$TMP/r.html" 2>/dev/null || true
echo "PDF -> $OUT ($(wc -c < "$OUT" 2>/dev/null || echo 0) bytes)"
