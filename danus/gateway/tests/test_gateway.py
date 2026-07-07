"""Tests for danus.gateway — role gating + tool wiring over danus.core.

The verify service is mocked (we replace ``server._verify``), so fact_submit is
exercised without a live verifier or codex. Config is read from the environment
at call time, so each test sets DANUS_* around a temp project dir.

Runs standalone (``python -m danus.gateway.tests.test_gateway``) and under pytest.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from danus.core import FactGraph, GlobalMemory
from danus.gateway import build_app, tools_for
from danus.gateway import server


@contextmanager
def _env(**kv):
    """Temporarily set env vars (None deletes), restore after."""
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def _mock_verify(verdict, repair_hints="", raise_exc=None):
    """Replace server._verify with a stub; restore after."""
    orig = server._verify

    def fake(statement, proof):
        if raise_exc is not None:
            raise raise_exc
        return {"verdict": verdict, "repair_hints": repair_hints,
                "verification_report": {"summary": "mock"}}

    server._verify = fake
    try:
        yield
    finally:
        server._verify = orig


def test_role_table():
    # main can never fabricate a fact
    assert "fact_submit" not in tools_for("main")
    assert "fact_revoke" in tools_for("main")
    # verifier is read-only: literature lookup ONLY
    assert tools_for("verifier") == ["search_arxiv_theorems"]
    # worker is the only role that can submit a fact
    assert "fact_submit" in tools_for("worker")
    # all three get the read view + literature grounding
    for r in ("worker", "main", "verifier"):
        assert "search_arxiv_theorems" in tools_for(r)
    # unknown / misconfigured role fails CLOSED to the read-only verifier set
    assert tools_for("nope") == tools_for("verifier")
    assert "fact_submit" not in tools_for("nope") and "gm_add" not in tools_for("nope")
    # build_app registers without error for every role
    for r in ("worker", "main", "verifier", "all"):
        assert build_app(r) is not None


def test_gm_and_fact_search_over_temp_project():
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="tester"
    ):
        out = server.gm_add("plan", claim="reduce to q>=2", evidence="")
        assert out["kind"] == "plan" and out["id"]
        hits = server.gm_search("reduce")
        assert hits["results_by_kind"]["plan"]["count"] == 1
        # fact_search over an empty graph is well-formed
        assert server.fact_search("anything")["results"] == []


def test_fact_submit_accept_writes_fact_and_traces():
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="worker_high",
        DANUS_VERIFY_URL="http://mock", DANUS_PROBLEM_ID="P",
    ), _mock_verify("correct"):
        res = server.fact_submit(statement="S(n)=n^2", proof="induction; QED")
        assert res["accepted"] is True and res["fact_id"]
        # the fact really landed in the graph
        fg = FactGraph(Path(d))
        assert fg.exists(res["fact_id"])
        # a verification trace was always written to global memory
        gm = GlobalMemory(Path(d))
        traces = gm.read("verification")
        assert traces and traces[-1]["verdict"] == "correct"
        assert traces[-1]["fact_id"] == res["fact_id"]


def test_fact_submit_reject_writes_nothing_but_traces():
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="worker_high",
        DANUS_VERIFY_URL="http://mock", DANUS_PROBLEM_ID="P",
    ), _mock_verify("wrong", repair_hints="gap in step 2"):
        res = server.fact_submit(statement="bad", proof="hand-wave")
        assert res["accepted"] is False and res["repair_hints"] == "gap in step 2"
        fg = FactGraph(Path(d))
        assert fg.list() == []  # nothing written
        gm = GlobalMemory(Path(d))
        assert gm.read("verification")[-1]["verdict"] == "wrong"  # but traced


def test_fact_submit_verify_error_is_clean():
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="w",
        DANUS_VERIFY_URL="http://mock", DANUS_PROBLEM_ID="P",
    ), _mock_verify("correct", raise_exc=RuntimeError("service down")):
        res = server.fact_submit(statement="s", proof="p")
        assert res["accepted"] is False and res["verdict"] == "error"
        assert "service down" in res["error"]


def test_fact_submit_accept_but_write_failed_still_traces():
    # a revoked predecessor makes FactGraph.add raise; the verdict is still traced
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="worker_high",
        DANUS_VERIFY_URL="http://mock", DANUS_PROBLEM_ID="P",
    ), _mock_verify("correct"):
        fg = FactGraph(Path(d))
        base = fg.add(problem_id="P", author="w", statement="A holds", proof="pf A")
        fg.revoke(base, reason="A was wrong")
        res = server.fact_submit(statement="B from A", proof="uses A", predecessors=[base])
        assert res["accepted"] is True and res["fact_id"] is None and res["write_error"]
        # verdict:correct is STILL traced even though the write failed
        assert GlobalMemory(Path(d)).read("verification")[-1]["verdict"] == "correct"


def test_fact_submit_glossary_check_never_blocks():
    # a raising undefined_symbols must not block submission (advisory heuristic)
    orig = FactGraph.undefined_symbols

    def boom(self, **kw):
        raise RuntimeError("glossary heuristic bug")

    FactGraph.undefined_symbols = boom
    try:
        with tempfile.TemporaryDirectory() as d, _env(
            DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="w",
            DANUS_VERIFY_URL="http://mock", DANUS_PROBLEM_ID="P",
        ), _mock_verify("correct"):
            res = server.fact_submit(statement="X thing", proof="because")
            assert res["accepted"] is True and res["undefined_symbols"] == []
    finally:
        FactGraph.undefined_symbols = orig


def test_fact_submit_nondict_verify_body_is_clean():
    # a valid-JSON but non-dict verify response must not crash the gate
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="w",
        DANUS_VERIFY_URL="http://mock", DANUS_PROBLEM_ID="P",
    ):
        orig = server._verify
        server._verify = lambda statement, proof: ["not", "a", "dict"]
        try:
            res = server.fact_submit(statement="s", proof="p")
            assert res["accepted"] is False and res["verdict"] == "error"
            assert "non-dict" in res["error"]
            assert FactGraph(Path(d)).list() == []  # nothing written
        finally:
            server._verify = orig


def test_role_env_default_and_build_app():
    # build_app(None) reads DANUS_ROLE (server._role) — exercises the env branch
    with _env(DANUS_ROLE="worker"):
        assert server._role() == "worker"
        app = build_app()  # role=None -> defaults to _role() (env)
        assert app is not None
    with _env(DANUS_ROLE=None):
        assert server._role() == "verifier"  # unset falls back read-only (fail-closed)


def test_project_by_name_without_agents_root_raises():
    # a project name is given but DANUS_AGENTS_ROOT is unset -> RuntimeError
    with _env(DANUS_AGENTS_ROOT=None, DANUS_PROJECT_DIR="/tmp/whatever"):
        try:
            server._project("proj_a")
            assert False, "should require DANUS_AGENTS_ROOT to resolve by name"
        except RuntimeError as e:
            assert "DANUS_AGENTS_ROOT" in str(e)


def test_verify_http_roundtrip_and_errors():
    # exercise the REAL _verify (local HTTP, offline-safe on 127.0.0.1)
    import http.server
    import threading

    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            captured["body"] = self.rfile.read(n).decode("utf-8")
            captured["ctype"] = self.headers.get("Content-Type")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"verdict": "correct", "verification_report": {"ok": true}}')

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/verify"
    try:
        # not set -> RuntimeError
        with _env(DANUS_VERIFY_URL=None):
            try:
                server._verify("s", "p")
                assert False, "should raise when DANUS_VERIFY_URL unset"
            except RuntimeError as e:
                assert "DANUS_VERIFY_URL" in str(e)
        # a real POST round-trip; the body is the JSON we sent
        with _env(DANUS_VERIFY_URL=url, DANUS_VERIFY_TIMEOUT="5"):
            out = server._verify("S(n)=n^2", "induction")
            assert out["verdict"] == "correct"
        assert '"statement": "S(n)=n^2"' in captured["body"]
        assert captured["ctype"] == "application/json"
        # a garbage timeout falls back to the default (no crash)
        with _env(DANUS_VERIFY_URL=url, DANUS_VERIFY_TIMEOUT="not-an-int"):
            assert server._verify("s", "p")["verdict"] == "correct"
    finally:
        srv.shutdown()


def test_fact_revoke_cascades():
    with tempfile.TemporaryDirectory() as d, _env(
        DANUS_PROJECT_DIR=d, DANUS_AGENTS_ROOT=None, DANUS_AUTHOR="main_agent",
    ):
        fg = FactGraph(Path(d))
        base = fg.add(problem_id="P", author="w", statement="A holds", proof="pf A")
        child = fg.add(problem_id="P", author="w", statement="B from A", proof="uses A",
                       predecessors=[base])
        out = server.fact_revoke(base, reason="A was wrong")
        assert set(out["revoked"]) == {base, child}
        assert not fg.exists(base) and not fg.exists(child)


def test_search_arxiv_theorems_delegates(monkeypatch=None):
    # the tool is a thin wrapper over danus.integrations.search; stub it (offline)
    orig = server._arxiv_search
    server._arxiv_search = lambda query, num_results=10: {
        "query": query, "num_results": num_results, "results": [{"title": "T"}]}
    try:
        out = server.search_arxiv_theorems("Beatty sequence", num_results=3)
        assert out["query"] == "Beatty sequence" and out["num_results"] == 3
        assert out["results"] == [{"title": "T"}]
    finally:
        server._arxiv_search = orig


def test_project_resolution_by_name_and_validation():
    with tempfile.TemporaryDirectory() as root:
        (Path(root) / "proj_a").mkdir()
        with _env(DANUS_AGENTS_ROOT=root, DANUS_PROJECT_DIR=None, DANUS_AUTHOR="main_agent"):
            # main addresses a project by name
            out = server.gm_add("master_guidance", claim="try route X", evidence="", project="proj_a")
            assert out["id"]
            assert GlobalMemory(Path(root) / "proj_a").read("master_guidance")
            # path-escape / bad names are rejected
            for bad in ("../evil", "a/b", "", "/abs"):
                try:
                    server.gm_search("x", project=bad)
                    assert False, f"should reject project name {bad!r}"
                except RuntimeError:
                    pass
            # unknown project rejected
            try:
                server.gm_search("x", project="missing")
                assert False, "should reject unknown project"
            except RuntimeError:
                pass


def test_main_module_builds_and_runs():
    # `python -m danus.gateway` builds an app from DANUS_ROLE and calls .run();
    # stub FastMCP.run so no stdio server actually starts.
    import runpy
    from mcp.server.fastmcp import FastMCP

    orig_run = FastMCP.run
    calls = {"n": 0}
    FastMCP.run = lambda self, *a, **k: calls.__setitem__("n", calls["n"] + 1)
    try:
        with _env(DANUS_ROLE="verifier"):
            runpy.run_module("danus.gateway", run_name="__main__")
        assert calls["n"] == 1
    finally:
        FastMCP.run = orig_run


def main() -> None:
    test_role_table()
    print("  [ok] role table (main no fact_submit; verifier read-only; worker submits)")
    test_role_env_default_and_build_app()
    print("  [ok] build_app reads DANUS_ROLE; _role default")
    test_project_by_name_without_agents_root_raises()
    print("  [ok] project-by-name without DANUS_AGENTS_ROOT -> RuntimeError")
    test_verify_http_roundtrip_and_errors()
    print("  [ok] _verify HTTP round-trip + unset-URL + bad-timeout fallback")
    test_fact_revoke_cascades()
    print("  [ok] fact_revoke cascades to descendants")
    test_search_arxiv_theorems_delegates()
    print("  [ok] search_arxiv_theorems delegates to integrations.search")
    test_main_module_builds_and_runs()
    print("  [ok] python -m danus.gateway builds app + calls run()")
    test_gm_and_fact_search_over_temp_project()
    print("  [ok] gm_add / gm_search / fact_search over a temp project")
    test_fact_submit_accept_writes_fact_and_traces()
    print("  [ok] fact_submit accept -> writes fact + verification trace")
    test_fact_submit_reject_writes_nothing_but_traces()
    print("  [ok] fact_submit reject -> writes nothing, still traces")
    test_fact_submit_verify_error_is_clean()
    print("  [ok] fact_submit verify-error -> clean error, no verdict")
    test_fact_submit_accept_but_write_failed_still_traces()
    print("  [ok] fact_submit accept-but-write-failed -> fact_id None + write_error, still traces correct")
    test_fact_submit_glossary_check_never_blocks()
    print("  [ok] fact_submit glossary heuristic never blocks submission")
    test_fact_submit_nondict_verify_body_is_clean()
    print("  [ok] fact_submit non-dict verify body -> clean error, nothing written")
    test_project_resolution_by_name_and_validation()
    print("  [ok] project resolution by name + path-escape validation")
    print("ALL GATEWAY TESTS PASSED")


if __name__ == "__main__":
    main()
