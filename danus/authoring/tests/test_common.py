"""Offline tests for danus.authoring.common — the shared renderer primitives.

Zero network / codex. Covers project resolution + path-escape validation, the
honesty outcome classifier, the frontmatter scrub, section wrapping, verbatim
file reads, and the generic leak scanner.

Runs standalone (``python -m danus.authoring.tests.test_common``) and under pytest.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from danus.authoring import common

from ._fixtures import env


def test_resolve_project_by_name_and_escape_validation():
    with tempfile.TemporaryDirectory() as root:
        proj = Path(root) / "odd_sum"
        proj.mkdir()
        with env(DANUS_AGENTS_ROOT=root, DANUS_PROJECT_DIR=None):
            assert common.resolve_project("odd_sum") == proj
            for bad in ("../evil", "a/b", "/abs"):
                try:
                    common.resolve_project(bad)
                    assert False, f"should reject {bad!r}"
                except RuntimeError:
                    pass
            # unknown but well-formed name
            try:
                common.resolve_project("nope")
                assert False, "unknown project should raise"
            except RuntimeError:
                pass


def test_resolve_project_by_name_without_agents_root_raises():
    # a project name given but DANUS_AGENTS_ROOT unset -> raise (common.py:45)
    with env(DANUS_AGENTS_ROOT=None, DANUS_PROJECT_DIR=None):
        try:
            common.resolve_project("some_proj")
            assert False, "project name without DANUS_AGENTS_ROOT should raise"
        except RuntimeError as e:
            assert "DANUS_AGENTS_ROOT" in str(e)


def test_body_sections_no_heading_strips_frontmatter_fence():
    # a malformed fact with NO '## ' body heading but a closing frontmatter fence:
    # the frontmatter must still be stripped, returning the post-fence content
    # (common.py:103-106).
    raw = "---\nfact_id: abc\nauthor: someone\n---\nSome loose body prose without headings.\n"
    body = common.body_sections(raw)
    assert "fact_id" not in body and "author" not in body
    assert "Some loose body prose without headings." in body


def test_body_sections_no_heading_no_frontmatter_returns_content():
    # no heading AND no frontmatter fence -> return the stripped content verbatim
    # (common.py:107, the final fallback).
    raw = "just a bare line of content\n"
    body = common.body_sections(raw)
    assert body.strip() == "just a bare line of content"


def test_body_sections_unterminated_frontmatter_returns_content():
    # an opening '---' with no closing fence -> the close-search yields None, so we
    # fall through to the raw fallback (common.py:107) rather than crashing.
    raw = "---\nfact_id: abc\nno closing fence here\n"
    body = common.body_sections(raw)
    assert body.strip().startswith("---")


def test_resolve_project_fallback_and_missing():
    with tempfile.TemporaryDirectory() as d:
        with env(DANUS_AGENTS_ROOT=None, DANUS_PROJECT_DIR=d):
            assert common.resolve_project() == Path(d)
        with env(DANUS_AGENTS_ROOT=None, DANUS_PROJECT_DIR=None):
            try:
                common.resolve_project()
                assert False, "no project + no PROJECT_DIR should raise"
            except RuntimeError:
                pass


def test_classify_outcome_ok_and_honesty_paths():
    ok = common.classify_outcome(
        subprocess.CompletedProcess(args=["x"], returncode=0, stdout="artifact body", stderr="warn"))
    assert ok["status"] == "ok" and ok["returncode"] == 0 and ok["stdout"] == "artifact body"

    nonzero = common.classify_outcome(
        subprocess.CompletedProcess(args=["x"], returncode=3, stdout="junk", stderr="boom"))
    assert nonzero["status"] == "error" and nonzero["returncode"] == 3 and "boom" in nonzero["stderr_tail"]

    empty = common.classify_outcome(
        subprocess.CompletedProcess(args=["x"], returncode=0, stdout="   \n", stderr=""),
        artifact_noun="report")
    assert empty["status"] == "error" and "no report" in empty["error"]

    timeout = common.classify_outcome(subprocess.TimeoutExpired(cmd="codex", timeout=1))
    assert timeout["status"] == "timeout"

    missing = common.classify_outcome(FileNotFoundError("/nope/codex"))
    assert missing["status"] == "error" and "not found" in missing["error"]


def test_body_sections_strips_frontmatter():
    raw = (
        "---\nfact_id: abc\nauthor: someone\npredecessors: [x]\n---\n"
        "## statement\nS(n)=n^2.\n## proof\nBy induction.\n"
    )
    body = common.body_sections(raw)
    assert body.startswith("## statement")
    assert "fact_id" not in body and "author" not in body and "predecessors" not in body
    assert "By induction." in body


def test_section_wraps_with_delimiters():
    s = common.section("NAME", "body text")
    assert "===== BEGIN NAME =====" in s and "===== END NAME =====" in s and "body text" in s


def test_read_fixed_and_read_project():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "f.md").write_text("hello", encoding="utf-8")
        assert common.read_fixed(Path(d), "f.md") == "hello"
        assert common.read_project(Path(d), "f.md") == "hello"
        for reader in (common.read_fixed, common.read_project):
            try:
                reader(Path(d), "missing.md")
                assert False, "missing file should raise"
            except FileNotFoundError:
                pass


def test_leak_findings_uses_supplied_patterns():
    patterns = [(r"\b[0-9a-f]{16}\b", "16-hex id"), (r"(?i)\bworker\b", "worker")]
    assert common.leak_findings("clean $n^2$ text", patterns) == []
    hits = common.leak_findings("see 161f436b1c2d3e4f and a worker", patterns)
    assert any("16-hex" in h for h in hits) and any("worker" in h for h in hits)
    # a pattern the caller did NOT supply is not flagged
    assert common.leak_findings("predecessors: [x]", patterns) == []


def main() -> None:
    test_resolve_project_by_name_and_escape_validation()
    print("  [ok] resolve_project by name + path-escape validation")
    test_resolve_project_fallback_and_missing()
    print("  [ok] resolve_project DANUS_PROJECT_DIR fallback + missing raises")
    test_resolve_project_by_name_without_agents_root_raises()
    print("  [ok] resolve_project by name without DANUS_AGENTS_ROOT raises")
    test_body_sections_no_heading_strips_frontmatter_fence()
    print("  [ok] body_sections no-heading -> strips frontmatter fence, keeps body")
    test_body_sections_no_heading_no_frontmatter_returns_content()
    print("  [ok] body_sections no-heading no-frontmatter -> content verbatim")
    test_body_sections_unterminated_frontmatter_returns_content()
    print("  [ok] body_sections unterminated frontmatter -> raw fallback")
    test_classify_outcome_ok_and_honesty_paths()
    print("  [ok] classify_outcome: ok / nonzero / empty / timeout / missing-binary")
    test_body_sections_strips_frontmatter()
    print("  [ok] body_sections strips frontmatter, keeps body verbatim")
    test_section_wraps_with_delimiters()
    print("  [ok] section wraps with BEGIN/END delimiters")
    test_read_fixed_and_read_project()
    print("  [ok] read_fixed / read_project verbatim + fail loud")
    test_leak_findings_uses_supplied_patterns()
    print("  [ok] leak_findings scans only the caller-supplied patterns")
    print("ALL COMMON TESTS PASSED")


if __name__ == "__main__":
    main()
