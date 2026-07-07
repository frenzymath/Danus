"""Whole-paper MATH verification — helpers for the whole-document gate.

Why the gate exists. The individual facts were each verified by the verify
service before they were written to the fact graph. But the paper is a DIFFERENT
artifact: the writer re-renders and re-stitches those facts for publication —
concising, dropping "obvious" steps, adding "it suffices to…", "WLOG…" glue, and
inline reductions that were never themselves a fact. Those seams are exactly where
a correct set of facts can become an incorrect paper. So the paper must be
re-verified as written, not trusted because its facts were.

How the gate works (``server.paper_verify_math``): the WHOLE document body is sent
as ONE input to a dedicated paper-math verifier codex (a fresh one-shot run — no
resident service, no fact graph, no slicing). The verifier reads the development
in order and judges self-containedness + correctness; a paper that leans on an
unproved lemma or undefined notation fails, correctly — the paper, not the
verifier, has to be complete. A body over ``whole_doc_budget`` is recorded
``too_large`` (an honest blocker): decomposing it by results into self-contained
parts — each culminating in a designated result — is the MAIN AGENT's job (see
the write-paper skill), never a hardcoded split here. A ``wrong`` verdict routes
back through ``paper_revise`` (gap-fill / notes), driven by the main agent.

This module is the deterministic, offline-testable half:

  * ``document_body`` / ``whole_doc_budget`` — the whole-doc input + size cap.
  * ledger read/write helpers + the ``deliver_ok`` gate (``VERIFY_LEDGER.md``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from danus.core._util import utc_now


def document_body(tex: str) -> str:
    """The ``\\begin{document}…\\end{document}`` body, or the whole string if no
    document environment (a bare excerpt). Used to scope block detection so the
    preamble is not mis-parsed as prose."""
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex, re.DOTALL)
    return m.group(1) if m else tex



# --------------------------------------------------------------------------- #
# ledger — the durable gate                                                    #
# --------------------------------------------------------------------------- #

# status values the ledger row can carry.
LEDGER_STATUSES = (
    "pending", "correct", "wrong", "unresolved-context", "oversized", "uncovered",
    "overridden", "trusted",
)
_LEDGER_HEADER = (
    "# VERIFY_LEDGER — whole-paper math verification\n\n"
    "<!-- ONLY the paper_verify_math tool writes verdict rows here. The main agent "
    "READS this file to know per-unit status + hints + attempts, and gates deliver "
    "on it (deliver is blocked unless every row is `correct` or `overridden`). The "
    "whole-paper gate writes one `whole-paper` row. -->\n"
)
_ROW_HEAD_RE = re.compile(r"^##\s+(\S+)\s*$")
_ROW_FIELD_RE = re.compile(r"^-\s+([A-Za-z_][\w-]*):\s*(.*)$")


@dataclass
class LedgerRow:
    unit_id: str
    label: str = ""
    source_fact: str = ""
    status: str = "pending"
    last_verdict: str = ""
    repair_hints: str = ""
    attempts: int = 0
    last_checked_utc: str = ""


def read_ledger(path: Path) -> Dict[str, LedgerRow]:
    """Parse VERIFY_LEDGER.md into ``{unit_id: LedgerRow}`` (empty if absent)."""
    rows: Dict[str, LedgerRow] = {}
    if not path.is_file():
        return rows
    cur: Optional[LedgerRow] = None
    for ln in path.read_text(encoding="utf-8").splitlines():
        h = _ROW_HEAD_RE.match(ln)
        if h:
            cur = LedgerRow(unit_id=h.group(1))
            rows[cur.unit_id] = cur
            continue
        if cur is None:
            continue
        f = _ROW_FIELD_RE.match(ln)
        if not f:
            continue
        key, val = f.group(1), f.group(2).strip()
        if key == "label":
            cur.label = val
        elif key == "source_fact":
            cur.source_fact = val
        elif key == "status":
            cur.status = val
        elif key == "last_verdict":
            cur.last_verdict = val
        elif key == "repair_hints":
            cur.repair_hints = val
        elif key == "attempts":
            try:
                cur.attempts = int(val)
            except ValueError:
                cur.attempts = 0
        elif key == "last_checked_utc":
            cur.last_checked_utc = val
    return rows


def write_ledger(path: Path, rows: List[LedgerRow]) -> None:
    """Rewrite VERIFY_LEDGER.md as a single always-current table (one ``## <unit_id>``
    row each, in the given order). ONLY the tool calls this."""
    parts = [_LEDGER_HEADER]
    for r in rows:
        parts.append(f"\n## {r.unit_id}")
        parts.append(f"- label: {r.label}")
        parts.append(f"- source_fact: {r.source_fact}")
        parts.append(f"- status: {r.status}")
        parts.append(f"- last_verdict: {r.last_verdict}")
        parts.append(f"- repair_hints: {r.repair_hints}")
        parts.append(f"- attempts: {r.attempts}")
        parts.append(f"- last_checked_utc: {r.last_checked_utc}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts).rstrip("\n") + "\n", encoding="utf-8")


def merge_attempts(prev: Dict[str, LedgerRow], unit_id: str) -> int:
    """Attempt count for a unit = prior attempts + 1 (a re-check is a new attempt).
    A brand-new unit_id starts at 1."""
    old = prev.get(unit_id)
    return (old.attempts if old else 0) + 1


def deliver_ok(path: Path) -> Tuple[bool, List[str]]:
    """The DELIVER GATE (deterministic, ledger-mediated). Returns
    ``(ok, blockers)``: deliver is allowed iff the ledger EXISTS and EVERY row is
    ``correct``, ``trusted``, or ``overridden``. ``correct`` = the verify service
    accepted the unit this run; ``trusted`` = the unit IS a single already-verified
    fact (accepted by the verify service at fact_submit — the fact graph is the
    correctness authority), presented faithfully and not re-verified in isolation;
    ``overridden`` = an operator override. ``blockers`` lists each offending
    ``<unit_id> (<status>)`` (and a single ``"no ledger"`` blocker if the ledger was
    never written — you cannot deliver a paper whose math was never checked). The
    main agent calls this before deliver; it reads the file, not its memory."""
    rows = read_ledger(path)
    if not rows:
        return False, ["no ledger (run paper_verify_math first)"]
    blockers: List[str] = []
    for r in rows.values():
        if r.status not in ("correct", "trusted", "overridden"):
            blockers.append(f"{r.unit_id} [{r.label}] ({r.status})")
    return (not blockers), blockers



def utc() -> str:
    return utc_now()


# --------------------------------------------------------------------------- #
# whole-document verification                                                  #
# --------------------------------------------------------------------------- #
#
# The paper-math verifier reads a FULL sequential development (definitions ->
# lemmas -> propositions -> the main theorem, in reading order) and judges, with
# NO external context, whether it is SELF-CONTAINED and correct. That is exactly
# the right test for a paper: a deliverable paper must stand on its own; a proof
# that leans on a lemma it never proves (or a fact_id / fact-graph context) is
# INCOMPLETE and must fail — the paper, not the verifier, has to be complete.
#
# We do NOT slice the paper into isolated per-theorem units and reconstruct a
# lossy fact-graph "grounding" (that both false-rejects delta proofs and hides
# incompleteness). One prompt, whole body. A prompt over ``whole_doc_budget`` is
# recorded ``too_large`` — decomposing by results into self-contained parts is
# the MAIN AGENT's job (see the write-paper skill), never a hardcoded split.


def whole_doc_budget() -> int:
    """Char budget for a SINGLE whole-paper verify call. Default ~700000 chars
    (~175K tokens, comfortably under a large verifier context). A prompt over this
    is recorded ``too_large`` — the main agent decomposes the paper by results
    into self-contained parts and drives them itself (see the write-paper skill);
    the tool never splits. Env override: ``DANUS_PAPER_VERIFY_WHOLE_DOC_CAP``
    (non-positive / unparseable → default)."""
    raw = os.environ.get("DANUS_PAPER_VERIFY_WHOLE_DOC_CAP", "")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 700000
    return n if n > 0 else 700000
