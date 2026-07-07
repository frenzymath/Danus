"""Offline tests for danus.human_summary.server — the summary_write tool.

Monkeypatches ``server.driver.run_codex`` with a fake CompletedProcess (no codex,
no network, no API). Verifies:
  - summary_write on clean codex output writes report.md, status ok, no leaks,
    small dict (no full report body leaked into the return);
  - a codex output that CONTAINS a fake fact_id is flagged by the leak check:
    status != ok, report.md is NOT kept, the leaky output is quarantined;
  - a nonzero codex exit is honest (status error, nothing written);
  - project resolution by name + path-escape validation.

Runs standalone (``python -m danus.human_summary.tests.test_server``) and under pytest.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path

from danus.human_summary import server

from ._fixtures import EXAMPLE_PROJECT, env, temp_project


@contextmanager
def _fake_codex(stdout="", returncode=0, stderr="", raise_exc=None):
    """Replace server.driver.run_codex with a stub returning a CompletedProcess."""
    orig = server.driver.run_codex

    def fake(prompt, *, model, effort, timeout=0):
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(args=["fake"], returncode=returncode,
                                           stdout=stdout, stderr=stderr)

    server.driver.run_codex = fake
    try:
        yield
    finally:
        server.driver.run_codex = orig


# a clean, id-free report body — passes the leak check
_CLEAN_REPORT = (
    "# Progress report\n\n"
    "## Precise problem statement\n"
    "For every integer $n \\ge 1$, $\\sum_{k=1}^{n}(2k-1) = n^2$.\n\n"
    "## Main mathematical progress\n"
    "We prove $S(n) = n^2$ by induction (proven).\n\n"
    "## Current status & next step\n"
    "$\\boxed{\\text{The identity holds for all } n \\ge 1.}$\n"
)

# a report body that leaks a 16-hex id (the exact failure mode this fix guards)
_LEAKY_REPORT = _CLEAN_REPORT + "\nSee fact 161f436b1c2d3e4f for details.\n"


def test_summary_write_leak_removes_stale_clean_report():
    # server.py:164 — a pre-existing clean report.md is removed when a fresh run leaks.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        report_path = pdir / "report" / "report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_CLEAN_REPORT, encoding="utf-8")  # stale clean artifact
        with _fake_codex(stdout=_LEAKY_REPORT, returncode=0):
            out = server.summary_write()
        assert out["status"] == "leak"
        assert not report_path.exists(), "the stale clean report.md must be removed on a leak"
        assert Path(out["leaky_md_path"]).exists()


def test_operator_language_missing_file(tmp_path=None):
    # server.py:102 — no OPERATOR.md -> None. Point _REPO_ROOT at a dir with no file.
    import tempfile
    orig = server._REPO_ROOT
    with tempfile.TemporaryDirectory() as d:
        server._REPO_ROOT = Path(d)
        try:
            assert server._operator_language() is None
        finally:
            server._REPO_ROOT = orig


def test_operator_language_blank_and_real():
    # server.py:104-108 — a real **Language:** line is picked up; the blank-template
    # placeholder "_( … )_" and a file with no Language line both -> None.
    import tempfile
    orig = server._REPO_ROOT
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        server._REPO_ROOT = root
        try:
            # real value
            (root / "OPERATOR.md").write_text("## Operator\n- **Language:** Chinese\n", encoding="utf-8")
            assert server._operator_language() == "Chinese"
            # blank-template placeholder -> None
            (root / "OPERATOR.md").write_text("- **Language:** _(fill in)_\n", encoding="utf-8")
            assert server._operator_language() is None
            # no Language line at all -> None (loop falls through: server.py:108)
            (root / "OPERATOR.md").write_text("## Operator\n- **Name:** x\n", encoding="utf-8")
            assert server._operator_language() is None
        finally:
            server._REPO_ROOT = orig


def test_summary_write_resolves_language_from_operator_md():
    # end-to-end: with no explicit language, summary_write reads OPERATOR.md.
    import tempfile
    orig = server._REPO_ROOT
    with tempfile.TemporaryDirectory() as d:
        server._REPO_ROOT = Path(d)
        (Path(d) / "OPERATOR.md").write_text("- **Language:** French\n", encoding="utf-8")
        try:
            with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
                    _fake_codex(stdout=_CLEAN_REPORT, returncode=0):
                out = server.summary_write()
                assert out["language"] == "French"
        finally:
            server._REPO_ROOT = orig


def test_build_app_registers_summary_write():
    # server.py:185-188 — build_app wires summary_write onto a FastMCP app.
    app = server.build_app()
    assert app is not None
    assert set(server._TOOLS) == {"summary_write"}


def test_main_module_runs_build_app():
    # __main__.py — `python -m danus.human_summary` builds the app and calls run().
    import runpy
    from mcp.server.fastmcp import FastMCP

    orig_run = FastMCP.run
    calls = {"n": 0}
    FastMCP.run = lambda self, *a, **k: calls.__setitem__("n", calls["n"] + 1)
    try:
        runpy.run_module("danus.human_summary", run_name="__main__")
    finally:
        FastMCP.run = orig_run
    assert calls["n"] == 1


def test_summary_write_clean_writes_report_and_status_ok():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_CLEAN_REPORT, returncode=0):
        out = server.summary_write()
        assert out["status"] == "ok" and out["returncode"] == 0
        assert out["leak_findings"] == []
        report_path = Path(out["report_md_path"])
        assert report_path.exists() and report_path.read_text(encoding="utf-8") == _CLEAN_REPORT
        # small return: the full report body is not leaked into the dict
        assert "stdout" not in out and _CLEAN_REPORT not in str(out)


def test_summary_write_leak_is_flagged_and_report_not_kept():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_LEAKY_REPORT, returncode=0):
        out = server.summary_write()
        # the fake fact_id is caught → not ok, and no clean report.md is produced
        assert out["status"] != "ok"
        assert out["leak_findings"], "the 16-hex id must be flagged"
        assert any("16-hex" in f for f in out["leak_findings"])
        assert not Path(out["report_md_path"]).exists(), "a leaky report must NOT be kept as report.md"
        # quarantined for inspection
        assert Path(out["leaky_md_path"]).exists()


def test_summary_write_nonzero_exit_is_honest_and_writes_nothing():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="partial", returncode=3, stderr="codex blew up"):
        out = server.summary_write()
        assert out["status"] == "error" and out["returncode"] == 3
        assert "codex blew up" in out["stderr_tail"]
        assert not Path(out["report_md_path"]).exists()


def test_summary_write_empty_stdout_is_honest():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="   \n", returncode=0):
        out = server.summary_write()
        assert out["status"] == "error" and "empty" in out["error"]
        assert not Path(out["report_md_path"]).exists()


def test_summary_write_timeout_is_honest():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(raise_exc=subprocess.TimeoutExpired(cmd="codex", timeout=1)):
        out = server.summary_write()
        assert out["status"] == "timeout"
        assert not Path(out["report_md_path"]).exists()


def test_leak_findings_catches_machinery_terms():
    # direct unit check of the leak scanner over each banned category
    assert server.leak_findings("clean text with $n^2$") == []
    assert server.leak_findings("author: example-worker")
    assert server.leak_findings("predecessors: [x]")
    assert server.leak_findings("see fact_odd_sum_main")
    assert server.leak_findings("per master_guidance")
    assert server.leak_findings("the verifier accepted it")
    assert server.leak_findings("a worker proved it")
    assert server.leak_findings("stored in global memory")


def test_project_resolution_by_name():
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as root:
        proj = Path(root) / "odd_sum"
        shutil.copytree(EXAMPLE_PROJECT, proj)
        with env(DANUS_AGENTS_ROOT=root, DANUS_PROJECT_DIR=None):
            with _fake_codex(stdout=_CLEAN_REPORT, returncode=0):
                out = server.summary_write(project="odd_sum")
            assert out["status"] == "ok"
            assert out["report_md_path"].startswith(str(proj))
            for bad in ("../evil", "a/b", "/abs"):
                try:
                    server.summary_write(project=bad)
                    assert False, f"should reject {bad!r}"
                except RuntimeError:
                    pass


def main() -> None:
    test_summary_write_clean_writes_report_and_status_ok()
    print("  [ok] summary_write clean output -> writes report.md, status ok, no leaks, small dict")
    test_summary_write_leak_is_flagged_and_report_not_kept()
    print("  [ok] summary_write leaked fact_id -> flagged, status != ok, report.md NOT kept")
    test_summary_write_leak_removes_stale_clean_report()
    print("  [ok] summary_write leak with a pre-existing clean report.md -> stale file removed")
    test_operator_language_missing_file()
    print("  [ok] _operator_language: missing OPERATOR.md -> None")
    test_operator_language_blank_and_real()
    print("  [ok] _operator_language: real value / blank placeholder / no line")
    test_summary_write_resolves_language_from_operator_md()
    print("  [ok] summary_write resolves language from OPERATOR.md when unset")
    test_build_app_registers_summary_write()
    print("  [ok] build_app wires summary_write")
    test_main_module_runs_build_app()
    print("  [ok] __main__ builds the app and calls run() once")
    test_summary_write_nonzero_exit_is_honest_and_writes_nothing()
    print("  [ok] summary_write nonzero exit -> status error, nothing written")
    test_summary_write_empty_stdout_is_honest()
    print("  [ok] summary_write empty stdout -> status error, nothing written")
    test_summary_write_timeout_is_honest()
    print("  [ok] summary_write timeout -> status timeout, nothing written")
    test_leak_findings_catches_machinery_terms()
    print("  [ok] leak_findings catches ids + author/predecessors/fact_ + machinery terms")
    test_project_resolution_by_name()
    print("  [ok] project resolution by name + path-escape validation")
    print("ALL SERVER TESTS PASSED")


if __name__ == "__main__":
    main()
