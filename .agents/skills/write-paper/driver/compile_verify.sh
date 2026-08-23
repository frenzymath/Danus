#!/usr/bin/env bash
# compile_verify.sh — the hard compile gate for a write-paper .tex.
#
#   bash compile_verify.sh <paper.tex>
#
# Compiles <paper.tex> with the LaTeX engine (auto-detected: pdflatex if installed,
# else tectonic; override with TEX_ENGINE=pdflatex|xelatex|lualatex|tectonic) TWICE
# (so \ref/\cite resolve on the second pass) in an isolated temp build dir (never
# pollutes the paper dir), then fails
# loudly unless the build is clean: zero LaTeX errors AND no "Citation undefined"
# / "Reference undefined" / "There were undefined references". On success prints
# the produced PDF path and size; on failure prints the offending log lines and
# exits non-zero. Skipping this gate is how broken .tex reaches the repo.
#
# TEX_ENGINE=tectonic uses Tectonic (a self-contained, perl-free engine that
# downloads packages on demand) — the zero-dependency option when no TeX Live is
# installed; it does its own multi-pass and writes no .log, so it gets a dedicated
# code path below.
set -u

# Engine selection: explicit TEX_ENGINE wins; otherwise auto-detect so a box with
# only Tectonic (no TeX Live) works with no env var — pdflatex if installed, else
# tectonic, else pdflatex (so the "not installed" error below fires clearly).
if [ -n "${TEX_ENGINE:-}" ]; then
  ENGINE="$TEX_ENGINE"
elif command -v pdflatex >/dev/null 2>&1; then
  ENGINE="pdflatex"
elif command -v tectonic >/dev/null 2>&1; then
  ENGINE="tectonic"
else
  ENGINE="pdflatex"
fi
case "$ENGINE" in
  pdflatex|xelatex|lualatex|tectonic) ;;
  *) echo "compile_verify: unsupported TEX_ENGINE '$ENGINE' — use pdflatex, xelatex, lualatex, or tectonic" >&2; exit 2;;
esac

TEX="${1:-}"
[ -n "$TEX" ] && [ -f "$TEX" ] || { echo "compile_verify: no such .tex: '$TEX'" >&2; exit 2; }
command -v "$ENGINE" >/dev/null 2>&1 || { echo "compile_verify: $ENGINE not installed — install a LaTeX toolchain (TeX Live or Tectonic); see the skill README" >&2; exit 3; }

TEX_ABS="$(cd "$(dirname "$TEX")" && pwd)/$(basename "$TEX")"
STEM="$(basename "${TEX%.tex}")"
BUILD="$(mktemp -d "${TMPDIR:-/tmp}/wp_compile_XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT
cp "$TEX_ABS" "$BUILD/$STEM.tex"

# Tectonic path: one invocation (it resolves \ref/\cite internally). Undefined
# refs/citations are LaTeX *warnings* that Tectonic keeps only in the .log (not on
# the console) and would exit 0 on — so we pass --keep-logs and grep that .log with
# the SAME patterns as the pdflatex gate, keeping the gate equally strict.
if [ "$ENGINE" = "tectonic" ]; then
  OUT="$BUILD/tectonic.out"
  ( cd "$BUILD" && tectonic --keep-logs --chatter minimal --outdir "$BUILD" "$STEM.tex" ) >"$OUT" 2>&1
  RC=$?
  LOG="$BUILD/$STEM.log"
  PDF="$BUILD/$STEM.pdf"
  fail=0; msg=""
  if [ $RC -ne 0 ] || [ ! -f "$PDF" ]; then
    fail=1; msg="tectonic exited $RC / no PDF produced"
  fi
  if grep -qiE '(^|[[:space:]])error:' "$OUT" 2>/dev/null || { [ -f "$LOG" ] && grep -qE '^!' "$LOG"; }; then
    fail=1; msg="${msg:+$msg; }LaTeX errors present"
  fi
  if [ -f "$LOG" ] && grep -qE 'Citation .* undefined|Reference .* undefined|There were undefined references' "$LOG"; then
    fail=1; msg="${msg:+$msg; }undefined citations/references"
  fi
  if [ $fail -ne 0 ]; then
    echo "COMPILE FAILED: $msg" >&2
    echo "--- offending output (l.NNN lines name the offending macro/token) ---" >&2
    { grep -iE 'error:' "$OUT" 2>/dev/null; grep -nE '^!|^l\.[0-9]+|Undefined control sequence|Citation .* undefined|Reference .* undefined|undefined references' "$LOG" 2>/dev/null; } | head -40 >&2
    exit 1
  fi
  SIZE=$(stat -c%s "$PDF" 2>/dev/null || stat -f%z "$PDF" 2>/dev/null || echo '?')
  OUT_PDF="$(dirname "$TEX_ABS")/$STEM.pdf"
  cp "$PDF" "$OUT_PDF"
  echo "COMPILE OK: $OUT_PDF ($SIZE bytes), no errors, no undefined citations [tectonic]"
  exit 0
fi

run() { ( cd "$BUILD" && "$ENGINE" -interaction=nonstopmode -halt-on-error "$STEM.tex" >/dev/null 2>&1 ); }
# first pass may legitimately report undefined refs; the second resolves them
run; RC=$?
run; RC=$?

LOG="$BUILD/$STEM.log"
PDF="$BUILD/$STEM.pdf"
fail=0; msg=""

if [ $RC -ne 0 ] || [ ! -f "$PDF" ]; then
  fail=1; msg="$ENGINE exited $RC / no PDF produced"
fi
# LaTeX hard errors (lines starting with '!') — show a few
if [ -f "$LOG" ] && grep -nE '^!' "$LOG" >/dev/null 2>&1; then
  fail=1; msg="${msg:+$msg; }LaTeX errors present"
fi
# undefined citations / references after the second pass
if [ -f "$LOG" ] && grep -nE 'Citation .* undefined|Reference .* undefined|There were undefined references' "$LOG" >/dev/null 2>&1; then
  fail=1; msg="${msg:+$msg; }undefined citations/references"
fi

if [ $fail -ne 0 ]; then
  echo "COMPILE FAILED: $msg" >&2
  echo "--- offending log lines (l.NNN lines name the offending macro/token) ---" >&2
  grep -nE '^!|^l\.[0-9]+|Undefined control sequence|Citation .* undefined|Reference .* undefined|undefined references|Runaway argument|Emergency stop' "$LOG" 2>/dev/null | head -40 >&2
  exit 1
fi

SIZE=$(stat -c%s "$PDF" 2>/dev/null || stat -f%z "$PDF" 2>/dev/null || echo '?')
OUT_PDF="$(dirname "$TEX_ABS")/$STEM.pdf"
cp "$PDF" "$OUT_PDF"
echo "COMPILE OK: $OUT_PDF ($SIZE bytes), no errors, no undefined citations"
