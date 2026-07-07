#!/usr/bin/env python3
"""A stand-in for the ``codex`` CLI, for PLUMBING tests of danus.authoring.driver.

The real driver runs ``codex exec ... -`` with the prompt on stdin and treats
stdout as the artifact (the .tex, the report, or the auditor report). This stub
does NOT do any LaTeX or judge any mathematics — it deterministically exercises
the driver's subprocess + stdin + stdout + returncode + cwd plumbing, with no
codex install and no API spend.

Behaviour (driven by markers in the stdin prompt, deterministic):
  - "[[FAKE:exit=N]]"  -> exit with code N (and empty stdout) — the honesty path
  - "[[FAKE:empty]]"   -> exit 0 with empty stdout            — the honesty path
  - "[[FAKE:cwd]]"     -> print the process cwd on stdout (for the cwd test)
  - otherwise          -> echo a tiny fixed .tex on stdout, exit 0

Point the driver at it with DANUS_CODEX_BIN=/abs/path/to/fake_codex.py . It
accepts (and ignores) the real codex flags; the prompt arrives on stdin.
"""
from __future__ import annotations

import os
import re
import sys

_FIXED_TEX = (
    "\\documentclass{amsart}\n"
    "\\begin{document}\n"
    "\\title{Fake}\n"
    "\\maketitle\n"
    "We prove that $S(n)=n^2$.\n"
    "% [[FAKE marker echoed for the gap test]]\n"
    "\\end{document}\n"
)


def main() -> int:
    prompt = sys.stdin.read()

    m = re.search(r"\[\[FAKE:exit=(\d+)\]\]", prompt)
    if m:
        sys.stderr.write("fake_codex: forced nonzero exit for the honesty path\n")
        return int(m.group(1))

    if "[[FAKE:empty]]" in prompt:
        return 0  # exit 0 but no stdout — the empty-artifact honesty path

    if "[[FAKE:cwd]]" in prompt:
        sys.stdout.write(os.getcwd())
        return 0

    # The default happy path: emit a tiny .tex, optionally carrying a GAP marker
    # so a server's [GAP:] parsing can be exercised.
    tex = _FIXED_TEX
    if "[[FAKE:gap]]" in prompt:
        tex += "% a hole: [GAP: missing step in the induction]\n"
    sys.stdout.write(tex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
