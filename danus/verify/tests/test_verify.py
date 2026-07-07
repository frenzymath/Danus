"""Offline tests for danus.verify — no codex, no API spend.

Prechecks are pure-function unit-tested; the full request path (pre-checks →
subprocess spawn → verification.json readback → verdict propagation) is exercised
by pointing DANUS_CODEX_BIN at ``fake_codex.py`` (a deterministic stub) and calling the
``/verify`` endpoint function directly (avoids an httpx TestClient dependency).

Runs standalone (``python -m danus.verify.tests.test_verify``) and under pytest.
"""

from __future__ import annotations

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from danus.verify import prechecks
from danus.verify.service import VerifyRequest, verify

FAKE = Path(__file__).resolve().parent / "fake_codex.py"

_GOOD_STATEMENT = "For every integer n, n + 0 equals n."
_GOOD_PROOF = (
    "Zero is the additive identity of the integers, so adding zero to any integer n "
    "leaves the value unchanged. Hence n + 0 = n for every integer n, as required."
)


@contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            os.environ[k] = v if v is not None else os.environ.get(k, "")
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _ensure_fake_executable():
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _call(statement, proof, tmp):
    with _env(DANUS_CODEX_BIN=str(FAKE)), \
            _env(VERIFIER_RESULTS_DIR=str(Path(tmp) / "runs"), VERIFY_AGENT_HOME=str(tmp)):
        return verify(VerifyRequest(statement=statement, proof=proof))


def test_prechecks_units():
    assert prechecks.is_vacuous_proof("QED")[0] is True
    assert prechecks.is_vacuous_statement("x")[0] is True
    assert prechecks.is_vacuous_proof(_GOOD_PROOF)[0] is False
    assert prechecks.check_problem_md_citation("The claim holds as declared in problem.md, done.") is not None
    assert prechecks.check_vague_gestures("As it is well known that the bound follows.") is not None
    assert prechecks.check_problem_md_citation(_GOOD_PROOF) is None
    # a real statement + proof passes every pre-check
    assert prechecks.run_prechecks(_GOOD_STATEMENT, _GOOD_PROOF) is None


def test_verify_accept_via_fake_codex():
    _ensure_fake_executable()
    with tempfile.TemporaryDirectory() as tmp:
        out = _call(_GOOD_STATEMENT, _GOOD_PROOF, tmp)
        assert out["verdict"] == "correct" and out["verification_report"]["critical_errors"] == []


def test_verify_reject_via_fake_codex():
    _ensure_fake_executable()
    with tempfile.TemporaryDirectory() as tmp:
        out = _call(_GOOD_STATEMENT, _GOOD_PROOF + " [[FAKE:wrong]]", tmp)
        assert out["verdict"] == "wrong" and out["repair_hints"]


def test_verify_vacuous_rejected_400():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _call("Trivial lemma about integers.", "QED", tmp)
            assert False, "vacuous proof should be rejected"
        except HTTPException as e:
            assert e.status_code == 400


def test_verify_precheck_p1_rejected_400():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _call("Some lemma that is self-contained and long enough to pass.",
                  "The result holds as declared in problem.md, which lists it as a verified "
                  "building block, so we are done with the argument here.", tmp)
            assert False, "P1 problem.md citation should be rejected"
        except HTTPException as e:
            assert e.status_code == 400


def main() -> None:
    test_prechecks_units()
    print("  [ok] prechecks units (vacuous + P1/P5 + clean passes)")
    test_verify_accept_via_fake_codex()
    print("  [ok] /verify accept via fake_codex -> verdict correct")
    test_verify_reject_via_fake_codex()
    print("  [ok] /verify reject via fake_codex ([[FAKE:wrong]]) -> verdict wrong")
    test_verify_vacuous_rejected_400()
    print("  [ok] /verify vacuous -> 400")
    test_verify_precheck_p1_rejected_400()
    print("  [ok] /verify P1 problem.md citation -> 400")
    print("ALL VERIFY TESTS PASSED")


if __name__ == "__main__":
    main()
