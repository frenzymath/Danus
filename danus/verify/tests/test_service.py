"""Offline HTTP-contract tests for danus.verify.service + __main__ entry.

Exercises the FastAPI app via TestClient with the launcher's codex-run
MONKEYPATCHED to a fake (no subprocess, no codex, no API spend), asserting the
POST /verify + GET /health contract and every error status mapping. The
``python -m danus.verify`` entrypoint is exercised via runpy with uvicorn.run
mocked so no server ever binds.

HTTP contract under test:
  POST /verify {statement, proof} -> 200 {verification_report, verdict, repair_hints}
  * 400 on a vacuous / precheck-failing input (before any codex run)
  * 422 on a schema-invalid body (missing/empty field — pydantic)
  * 504 on codex timeout, 500 on exit / missing-output / bad-json (launcher raises)
  GET /health -> 200 {status: "ok"}

Runs standalone (``python -m danus.verify.tests.test_service``) and under pytest.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.testclient import TestClient

from danus.verify import service

_STMT = "For every integer n, n + 0 equals n."
_PROOF = (
    "Zero is the additive identity of the integers, so adding zero to any integer n "
    "leaves the value unchanged. Hence n + 0 = n for every integer n, as required."
)

_CANNED_OK = {
    "verification_report": {"summary": "fake accept", "critical_errors": [], "gaps": []},
    "verdict": "correct",
    "repair_hints": "",
}


@contextmanager
def _fake_run(fn):
    """Replace the launcher's codex-run (imported into service) with a fake."""
    orig_run = service.run_codex_verification
    orig_alloc = service._allocate_run_id
    service.run_codex_verification = fn
    service._allocate_run_id = lambda statement: "RID-fake"
    try:
        yield
    finally:
        service.run_codex_verification = orig_run
        service._allocate_run_id = orig_alloc


def _client():
    return TestClient(service.app)


# --------------------------------------------------------------------------- #
# /health                                                                     #
# --------------------------------------------------------------------------- #

def test_health_ok():
    resp = _client().get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # /health self-identifies with the serving process pid (callers match it
    # against runtime/run/verify.pid to distinguish OUR verify from a foreign
    # deployment holding the same port on a shared host).
    assert isinstance(body["pid"], int) and body["pid"] > 0


# --------------------------------------------------------------------------- #
# /verify — happy path                                                        #
# --------------------------------------------------------------------------- #

def test_verify_accept_contract():
    def fake(run_id, statement, proof):
        assert run_id == "RID-fake"  # allocator was used
        return _CANNED_OK

    with _fake_run(fake):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": _PROOF})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "correct"
    assert body["verification_report"]["critical_errors"] == []
    assert "repair_hints" in body


def test_verify_reject_verdict_still_200():
    # a "wrong" verdict is a normal 200 response (the verdict is the payload).
    canned = dict(_CANNED_OK, verdict="wrong", repair_hints="fix the gap")
    with _fake_run(lambda run_id, statement, proof: canned):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": _PROOF})
    assert resp.status_code == 200 and resp.json()["verdict"] == "wrong"


# --------------------------------------------------------------------------- #
# /verify — precheck rejections happen BEFORE any codex run (400)             #
# --------------------------------------------------------------------------- #

def _must_not_run(*a, **k):
    raise AssertionError("codex must not run when a precheck rejects")


def test_verify_vacuous_proof_400():
    with _fake_run(_must_not_run):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": "QED"})
    assert resp.status_code == 400 and "vacuous proof" in resp.json()["detail"]


def test_verify_p1_precheck_400():
    bad = ("The result holds as declared in problem.md, which lists it as a verified "
           "building block, so we are done with the argument here.")
    with _fake_run(_must_not_run):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": bad})
    assert resp.status_code == 400 and "[P1 on proof]" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# /verify — launcher error mappings surface as the raised status              #
# --------------------------------------------------------------------------- #

def _raiser(status, detail):
    def fn(run_id, statement, proof):
        raise HTTPException(status_code=status, detail=detail)
    return fn


def test_verify_timeout_504():
    with _fake_run(_raiser(504, "codex exec timed out after 900s")):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": _PROOF})
    assert resp.status_code == 504 and "timed out" in resp.json()["detail"]


def test_verify_exit_500():
    with _fake_run(_raiser(500, "codex exec failed with exit code 7")):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": _PROOF})
    assert resp.status_code == 500 and "exit code" in resp.json()["detail"]


def test_verify_missing_output_500():
    with _fake_run(_raiser(500, "verification output was not found")):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": _PROOF})
    assert resp.status_code == 500 and "was not found" in resp.json()["detail"]


def test_verify_bad_json_500():
    with _fake_run(_raiser(500, "verification output ... is not valid JSON")):
        resp = _client().post("/verify", json={"statement": _STMT, "proof": _PROOF})
    assert resp.status_code == 500 and "not valid JSON" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# /verify — schema validation (pydantic, 422) before prechecks               #
# --------------------------------------------------------------------------- #

def test_verify_empty_field_422():
    with _fake_run(_must_not_run):
        resp = _client().post("/verify", json={"statement": "", "proof": _PROOF})
    assert resp.status_code == 422


def test_verify_missing_field_422():
    with _fake_run(_must_not_run):
        resp = _client().post("/verify", json={"statement": _STMT})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# `python -m danus.verify` entry — uvicorn mocked, no bind                    #
# --------------------------------------------------------------------------- #

def test_main_entry_runs_uvicorn(monkeypatch):
    import os
    import runpy

    calls = {}
    fake_uvicorn = types.ModuleType("uvicorn")

    def fake_run(app, host, port):  # noqa: ANN001
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    fake_uvicorn.run = fake_run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setenv("VERIFY_HOST", "127.0.0.1")
    monkeypatch.setenv("VERIFY_PORT", "8199")
    monkeypatch.delenv("CODEX_TIMEOUT_SECONDS", raising=False)

    runpy.run_module("danus.verify", run_name="__main__")

    assert calls["host"] == "127.0.0.1" and calls["port"] == 8199
    assert calls["app"] is not None
    # the entrypoint sets a bounded default per-verification timeout
    assert os.environ.get("CODEX_TIMEOUT_SECONDS") == "900"


def main() -> None:
    import inspect

    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if inspect.signature(fn).parameters:
                print(f"  [skip standalone] {name} (needs pytest fixture)")
                continue
            fn()
            print(f"  [ok] {name}")
    print("ALL SERVICE TESTS PASSED")


if __name__ == "__main__":
    main()
