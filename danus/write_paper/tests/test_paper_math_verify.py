"""Offline tests for the whole-paper MATH verification gate.

Two layers, both offline:
  * ``paper_math_verify`` — the deterministic helpers: ledger + deliver gate
    and the whole-doc budget;
  * ``server.paper_verify_math`` — the MCP tool, with the paper-math verifier
    codex faked (``server._drive`` monkeypatched) so ``correct``/``wrong``
    verdicts, a failed run, and ``too_large`` are all exercised offline.

Runs under pytest and standalone (``python -m
danus.write_paper.tests.test_paper_math_verify``).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from danus.write_paper import assemble
from danus.write_paper import paper_math_verify as pmv
from danus.write_paper import server

from ._fixtures import env, temp_project

# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #

# A two-result paper: a main theorem that \ref's a lemma, the lemma, plus a
# reduction glue claim. The example fact graph carries the matching facts
# (fact_odd_sum_main / fact_odd_recurrence), mapped by _PROV below.
_MULTI_TEX = (
    "\\documentclass{amsart}\n"
    "\\newcommand{\\Sn}{S(n)}\n"
    "\\begin{document}\n"
    "\\title{Odd sums}\\maketitle\n"
    "\\begin{lemma}\\label{lem:rec} For $n\\ge1$, $S(n+1)=S(n)+(2n+1)$. \\end{lemma}\n"
    "\\begin{proof} The $(n+1)$-st odd number is $2n+1$, as in \\cite{AC24}. \\end{proof}\n"
    "\\begin{thm}\\label{thm:main} For all $n\\ge1$, $\\Sn=n^2$. \\end{thm}\n"
    "\\begin{proof} By induction using \\ref{lem:rec}; see \\cite{Exm20}. \\end{proof}\n"
    "\n"
    "It suffices to prove the recurrence, since the rest follows by induction on $n$."
    " This is standard.\n"
    "\\end{document}\n"
)

# label -> source fact id (the writer's %%%PROVENANCE%%% map for _MULTI_TEX).
_PROV = {"thm:main": "fact_odd_sum_main", "lem:rec": "fact_odd_recurrence"}

# A paper whose only proof is an ORPHAN (attached to no labeled result).
_ORPHAN_TEX = (
    "\\documentclass{amsart}\n"
    "\\begin{document}\n"
    "\\begin{proof} An argument that belongs to no theorem. \\end{proof}\n"
    "\\end{document}\n"
)


@contextmanager
def _fake_drive(verdict="correct", hints="", report="ok", ok=True):
    """Fake ``server._drive`` (the THIRD verifier's codex). ``ok`` False → a non-ok
    codex run (verify_error path); else a clean run whose stdout ends with the
    verdict JSON the paper-math verifier is contracted to emit."""
    orig = server._drive

    def fake(prompt, effort=None):
        if not ok:
            return {"status": "error", "returncode": 1, "stdout": "",
                    "stderr_tail": "boom", "error": "verifier codex failed"}
        payload = json.dumps({"verdict": verdict, "repair_hints": hints, "report": report})
        return {"status": "ok", "returncode": 0,
                "stdout": f"(analysis of the paper …)\n{payload}\n", "stderr_tail": ""}

    server._drive = fake
    try:
        yield
    finally:
        server._drive = orig


def _write_prov(pdir: Path, prov: Dict[str, Any], paper_id: Optional[str] = None) -> Path:
    """Write the writer's ``.provenance.json`` (label → source fact id) into the
    paper workspace (`.provenance.json`, the label → fact-id side file)."""
    ws = assemble.paper_workspace(Path(pdir), paper_id)
    ws.mkdir(parents=True, exist_ok=True)
    path = ws / ".provenance.json"
    path.write_text(json.dumps(prov, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# ledger + deliver gate                                                         #
# --------------------------------------------------------------------------- #

def test_ledger_roundtrip_and_deliver_gate():
    with temp_project(with_ledger=True) as pdir:
        path = pdir / "paper" / "VERIFY_LEDGER.md"
        rows = [
            pmv.LedgerRow(unit_id="u001", label="thm:main", status="correct",
                          last_verdict="correct", attempts=1),
            pmv.LedgerRow(unit_id="u002", label="lem:rec", status="wrong",
                          last_verdict="wrong", repair_hints="gap in step 2", attempts=2),
        ]
        pmv.write_ledger(path, rows)
        back = pmv.read_ledger(path)
        assert back["u002"].status == "wrong"
        assert back["u002"].attempts == 2
        ok, blockers = pmv.deliver_ok(path)
        assert not ok
        assert any("u002" in b for b in blockers)

        rows[1].status = "correct"
        pmv.write_ledger(path, rows)
        ok, blockers = pmv.deliver_ok(path)
        assert ok and blockers == []


def test_deliver_gate_blocks_when_no_ledger():
    with temp_project(with_ledger=True) as pdir:
        ok, blockers = pmv.deliver_ok(pdir / "paper" / "VERIFY_LEDGER.md")
        assert not ok and blockers == ["no ledger (run paper_verify_math first)"]


def test_deliver_gate_blocks_oversized_and_unresolved_allows_overridden():
    with temp_project(with_ledger=True) as pdir:
        path = pdir / "paper" / "VERIFY_LEDGER.md"
        pmv.write_ledger(path, [
            pmv.LedgerRow(unit_id="u001", label="t", status="correct"),
            pmv.LedgerRow(unit_id="u002", label="u", status="oversized"),
            pmv.LedgerRow(unit_id="u003", label="v", status="unresolved-context"),
        ])
        ok, blockers = pmv.deliver_ok(path)
        assert not ok
        assert any("oversized" in b for b in blockers)
        assert any("unresolved-context" in b for b in blockers)
        # operator override on both → deliver unblocked (visibly flagged in the paper)
        pmv.write_ledger(path, [
            pmv.LedgerRow(unit_id="u001", label="t", status="correct"),
            pmv.LedgerRow(unit_id="u002", label="u", status="overridden"),
            pmv.LedgerRow(unit_id="u003", label="v", status="overridden"),
        ])
        ok, blockers = pmv.deliver_ok(path)
        assert ok and blockers == []


# --------------------------------------------------------------------------- #
# the tool: correct / wrong / unresolved / honest verify-failure               #
# --------------------------------------------------------------------------- #

def test_tool_all_correct_reports_passed():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="0"):
        (pdir / "paper" / "main.tex").write_text(_MULTI_TEX, encoding="utf-8")
        # WHOLE-DOC: the paper is verified as ONE self-contained development; a
        # 'correct' verdict on the whole document → passed + deliver_ok.
        with _fake_drive(verdict="correct"):
            out = server.paper_verify_math()
        assert out["status"] == "passed", out
        assert out["wrong"] == 0
        assert out["deliver_ok"] is True
        assert out["verdict"] == "correct"
        assert out["units_total"] == 1 and out["correct"] == 1


def test_tool_wrong_whole_doc_blocks_with_hints():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="0"):
        (pdir / "paper" / "main.tex").write_text(_MULTI_TEX, encoding="utf-8")
        # a 'wrong' verdict on the whole document (e.g. it uses an unproved lemma) →
        # blocked, with the verifier's repair hints recorded on the single row.
        with _fake_drive(verdict="wrong",
                         hints="prove the missing lemma before resubmitting"):
            out = server.paper_verify_math()
        assert out["status"] == "blocked", out
        assert out["wrong"] == 1
        assert out["deliver_ok"] is False
        rows = pmv.read_ledger(Path(out["ledger_path"]))
        assert list(rows) == ["whole-paper"]
        assert "missing lemma" in rows["whole-paper"].repair_hints


def test_tool_too_large_paper_not_sent():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="0",
                DANUS_PAPER_VERIFY_WHOLE_DOC_CAP="100"):
        (pdir / "paper" / "main.tex").write_text(_MULTI_TEX, encoding="utf-8")
        calls = {"n": 0}
        orig = server._drive

        def counting(prompt, effort=None):
            calls["n"] += 1
            return {"status": "ok", "stdout": '{"verdict": "correct"}'}

        server._drive = counting
        try:
            out = server.paper_verify_math()
        finally:
            server._drive = orig
        # a body over the single whole-doc call budget is NOT sent (main-agent
        # decomposition by results needed) — recorded honestly, never a false pass.
        assert calls["n"] == 0
        assert out["status"] == "too_large"
        assert out["deliver_ok"] is False


def test_tool_never_reports_passed_on_failed_verify_run():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="0"):
        (pdir / "paper" / "main.tex").write_text(_MULTI_TEX, encoding="utf-8")
        with _fake_drive(ok=False):
            out = server.paper_verify_math()
        assert out["status"] == "verify_error", out
        assert out["deliver_ok"] is False
        assert "error" in out
        rows = pmv.read_ledger(Path(out["ledger_path"]))
        assert all(r.status != "correct" for r in rows.values())


def test_tool_orphan_proof_whole_doc_wrong_blocks():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="0"):
        (pdir / "paper" / "main.tex").write_text(_ORPHAN_TEX, encoding="utf-8")
        # a paper whose "proof" belongs to no theorem is not self-contained → the
        # whole-doc verifier returns wrong → blocked (no per-unit 'uncovered' concept).
        with _fake_drive(verdict="wrong", hints="orphan proof attached to no result"):
            out = server.paper_verify_math()
        assert out["deliver_ok"] is False
        assert out["status"] == "blocked"


def test_tool_returns_log_path_and_writes_ledger():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="1"):
        (pdir / "paper" / "main.tex").write_text(_MULTI_TEX, encoding="utf-8")
        _write_prov(pdir, _PROV)
        with _fake_drive(verdict="correct"):
            out = server.paper_verify_math()
        assert out["log_path"] and Path(out["log_path"]).is_file()
        assert Path(out["ledger_path"]).is_file()


def test_tool_no_paper_is_honest():
    with temp_project(with_ledger=True) as pdir, \
            env(DANUS_PROJECT_DIR=str(pdir), DANUS_WRITE_PAPER_RUN_LOG="0"):
        out = server.paper_verify_math()
        assert out["status"] == "no_paper"
        assert out["deliver_ok"] is False


def test_tool_registered_in_app():
    assert "paper_verify_math" in server._TOOLS


# --------------------------------------------------------------------------- #
# standalone runner                                                            #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} tests passed")
    sys.exit(0)
