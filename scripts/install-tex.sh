#!/usr/bin/env bash
# install-tex.sh — OPTIONAL: install a LaTeX engine for the write-paper compile gate.
#
# LaTeX is a prerequisite of the write-paper skill ONLY (its compile gate,
# driver/compile_verify.sh). Nothing else in Danus needs it, so it is deliberately
# NOT part of scripts/bootstrap.sh — run this only if you want to produce papers.
#
#   bash scripts/install-tex.sh            # install Tectonic (default)
#
# Default engine: Tectonic — a self-contained, perl-free LaTeX engine (a single
# static binary that downloads packages on demand). It is the zero-dependency
# option and works on minimal hosts where TeX Live's perl-based tooling
# (install-tl / tlmgr / TinyTeX) cannot run. Installs to ~/.local/bin.
#
# After install, point the compile gate at it with:  export TEX_ENGINE=tectonic
# (and ensure ~/.local/bin is on PATH). pdflatex/xelatex/lualatex from a system
# TeX Live also work — this script just gives you a no-root path when you have none.
set -euo pipefail

BIN_DIR="${TECTONIC_BIN_DIR:-$HOME/.local/bin}"

if command -v tectonic >/dev/null 2>&1; then
  echo "[install-tex] tectonic already on PATH: $(command -v tectonic) ($(tectonic --version 2>/dev/null))"
  echo "[install-tex] nothing to do. Use it with: export TEX_ENGINE=tectonic"
  exit 0
fi

echo "[install-tex] installing Tectonic (user-level, no root) into $BIN_DIR ..."
mkdir -p "$BIN_DIR"
( cd "$BIN_DIR" && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh )

if [ ! -x "$BIN_DIR/tectonic" ]; then
  echo "[install-tex] ERROR: tectonic was not installed to $BIN_DIR" >&2
  exit 1
fi

echo "[install-tex] done: $BIN_DIR/tectonic ($("$BIN_DIR/tectonic" --version 2>/dev/null))"
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) echo "[install-tex] NOTE: add $BIN_DIR to PATH, e.g.  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
echo "[install-tex] then run the write-paper compile gate with:  export TEX_ENGINE=tectonic"
