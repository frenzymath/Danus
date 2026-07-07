"""Offline tests for danus.observability — the CLI entry (main / __main__) and the
loader guard branches. Zero network; uvicorn is faked, no server is bound.

Runs standalone (``python -m danus.observability.tests.test_observability_main``)
and under pytest.
"""

from __future__ import annotations

import contextlib
import os
import runpy
import sys
import tempfile
import types
from pathlib import Path

import sys

import danus.observability.app  # ensure the submodule is imported into sys.modules

# The package __init__ re-exports the FastAPI instance as danus.observability.app,
# which shadows the submodule on attribute access — so reach the MODULE via sys.modules.
app = sys.modules["danus.observability.app"]

_MIN_FACT = (
    "---\n"
    "fact_id: g1\n"
    "problem_id: P\n"
    "author: w\n"
    "predecessors: []\n"
    "glossary_introduces: {}\n"
    "external_refs: []\n"
    "---\n"
    "## statement\nS\n## proof\nP\n"
)


@contextlib.contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


@contextlib.contextmanager
def _argv(*args):
    old = sys.argv[:]
    sys.argv = ["dashboard", *args]
    try:
        yield
    finally:
        sys.argv = old


def test_project_dir_unset_raises():
    with _env(DANUS_DASHBOARD_PROJECT=None, DANUS_PROJECT_DIR=None):
        try:
            app._project_dir()
            assert False, "unset project dir should raise"
        except RuntimeError:
            pass


def test_main_project_not_found_fails_fast():
    with tempfile.TemporaryDirectory() as d:
        missing = str(Path(d) / "nope")
        with _env(DANUS_DASHBOARD_PROJECT=missing), _argv():
            try:
                app.main()
                assert False, "a missing project dir should SystemExit"
            except SystemExit as e:
                assert "project dir not found" in str(e)


def test_main_happy_path_runs_uvicorn():
    fake = types.ModuleType("uvicorn")
    calls = {}
    fake.run = lambda application, **kw: calls.update(kw, application=application)
    with tempfile.TemporaryDirectory() as d, _env(DANUS_DASHBOARD_PROJECT=None), _argv("--project", d, "--host", "127.0.0.1", "--port", "9137"):
        sys.modules["uvicorn"] = fake
        try:
            app.main()
        finally:
            sys.modules.pop("uvicorn", None)
    assert calls.get("host") == "127.0.0.1" and calls.get("port") == 9137
    assert calls.get("application") is app.app


def test_module_entrypoint_runs_main():
    orig = app.main
    ran = {"v": False}
    app.main = lambda: ran.__setitem__("v", True)
    try:
        runpy.run_module("danus.observability", run_name="__main__")
    finally:
        app.main = orig
    assert ran["v"] is True


def test_load_facts_skips_unreadable_and_idless():
    with tempfile.TemporaryDirectory() as d:
        facts = Path(d) / "fact_graph" / "facts"
        facts.mkdir(parents=True)
        (facts / "good.md").write_text(_MIN_FACT, encoding="utf-8")
        (facts / "bad.md").mkdir()  # a dir named *.md -> read_text raises OSError -> skipped
        out = app._load_facts(Path(d))
        assert [f["fact_id"] for f in out] == ["g1"]


def test_load_jsonl_unreadable_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "chan.jsonl"
        p.mkdir()  # a dir -> read_text raises OSError -> []
        assert app._load_jsonl(p) == []


def test_parse_fact_frontmatter_line_without_colon():
    txt = "---\njust-a-bare-line\nfact_id: f9\n---\n## statement\nS\n## proof\nP\n"
    fact = app._parse_fact(txt)
    assert fact["fact_id"] == "f9"  # the colonless frontmatter line is skipped, not fatal


def test_load_jsonl_permission_denied_returns_empty():
    import stat
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "chan.jsonl"
        p.write_text('{"a": 1}\n', encoding="utf-8")
        p.chmod(0)  # exists + is_file, but unreadable -> read_text raises OSError -> []
        try:
            assert app._load_jsonl(p) == []
        finally:
            p.chmod(stat.S_IRUSR | stat.S_IWUSR)  # restore so tempdir cleanup succeeds


def test_app_module_run_as_main():
    # run app.py itself as __main__ so its bottom `if __name__ == "__main__": main()` fires
    fake = types.ModuleType("uvicorn")
    fake.run = lambda application, **kw: None
    with tempfile.TemporaryDirectory() as d, _env(DANUS_DASHBOARD_PROJECT=d), _argv():
        sys.modules["uvicorn"] = fake
        try:
            runpy.run_module("danus.observability.app", run_name="__main__")
        finally:
            sys.modules.pop("uvicorn", None)


def main() -> None:
    test_project_dir_unset_raises()
    print("  [ok] _project_dir raises when unset")
    test_main_project_not_found_fails_fast()
    print("  [ok] main() fails fast when the project dir is missing")
    test_main_happy_path_runs_uvicorn()
    print("  [ok] main() runs uvicorn on the given host/port (faked)")
    test_module_entrypoint_runs_main()
    print("  [ok] python -m danus.observability calls main()")
    test_load_facts_skips_unreadable_and_idless()
    print("  [ok] _load_facts skips an unreadable *.md entry")
    test_load_jsonl_unreadable_returns_empty()
    print("  [ok] _load_jsonl returns [] on an unreadable path")
    test_parse_fact_frontmatter_line_without_colon()
    print("  [ok] _parse_fact tolerates a colonless frontmatter line")
    test_load_jsonl_permission_denied_returns_empty()
    print("  [ok] _load_jsonl returns [] on an unreadable (exists-but-denied) file")
    test_app_module_run_as_main()
    print("  [ok] app.py run as __main__ fires its main() guard")
    print("ALL OBSERVABILITY-MAIN TESTS PASSED")


if __name__ == "__main__":
    main()
