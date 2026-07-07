#!/usr/bin/env python3
"""A stand-in for the `codex` CLI, for PLUMBING tests of the verify service.

The real service cold-starts `codex exec ... <prompt>`; the codex agent reads
AGENTS.md, judges the proof, and writes verification.json to the path named in
the prompt. This stub does NOT judge any mathematics -- it only exercises the
service's subprocess + file-readback + verdict-propagation plumbing
deterministically, with no codex install and no API spend.

Verdict rule (deterministic, plumbing only):
  - prompt contains "[[FAKE:wrong]]"  -> verdict "wrong"
  - otherwise                         -> verdict "correct"

Point the service at it with DANUS_CODEX_BIN=/abs/path/to/fake_codex.py . It accepts
(and ignores) the real codex flags; the prompt is the final argv entry.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("fake_codex: no prompt argument\n")
        return 2
    prompt = sys.argv[-1]

    m = re.search(r"this exact path:\s*(\S+)", prompt)
    if not m:
        sys.stderr.write("fake_codex: could not find output path in prompt\n")
        return 3
    out_path = Path(m.group(1).rstrip("."))

    if "[[FAKE:wrong]]" in prompt:
        payload = {
            "verification_report": {
                "summary": "FAKE stub verdict (plumbing test): marker [[FAKE:wrong]] present.",
                "critical_errors": [
                    {"location": "proof", "issue": "fake_codex injected critical error for the reject path"}
                ],
                "gaps": [],
            },
            "verdict": "wrong",
            "repair_hints": "This is a fake reject from fake_codex.py (plumbing only).",
        }
    else:
        payload = {
            "verification_report": {
                "summary": "FAKE stub verdict (plumbing test): no error marker; accepting.",
                "critical_errors": [],
                "gaps": [],
            },
            "verdict": "correct",
            "repair_hints": "",
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    sys.stdout.write(f"fake_codex: wrote {payload['verdict']} verdict to {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
