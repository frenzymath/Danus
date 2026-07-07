"""Offline tests for danus.human_summary.assemble — embed-completeness + scrub.

Zero network / API / codex. Asserts:
  - the assembled prompt embeds the writer prompt + PROBLEM.md verbatim + the
    fact proof text (the mathematics is present);
  - the ISOLATION / SCRUB contract: NO fact_id, NO 'author:', NO 'predecessors',
    no frontmatter of any kind reaches the writer;
  - a missing required file raises.

Runs standalone (``python -m danus.human_summary.tests.test_assemble``) and under pytest.
"""

from __future__ import annotations

from pathlib import Path

from danus.human_summary import assemble

from ._fixtures import SKILL_DIR, env, temp_project


def _writer_prompt() -> str:
    return (SKILL_DIR / "REPORT_WRITER_PROMPT.md").read_text(encoding="utf-8")


def test_embeds_writer_prompt_problem_and_proof_verbatim():
    with temp_project() as pdir:
        p = assemble.build_prompt(pdir)
    # the fixed writer prompt, verbatim
    assert _writer_prompt() in p
    assert "REPORT WRITER" in p
    # PROBLEM.md verbatim (its distinctive goal line)
    assert "the sum of the\nfirst $n$ positive odd numbers equals $n^2$" in p \
        or "sum of the first $n$ positive odd numbers" in p
    assert "**Goal (verbatim).**" in p
    # each fact's ## proof / ## intuition body text (verbatim math is preserved)
    assert "By induction on $n$" in p                                   # main proof
    assert "the partial-sum recurrence" in p                           # main proof
    assert "Expand $(n+1)^2 = n^2 + 2n + 1 = n^2 + (2n+1)$" in p        # square proof
    # section delimiters present so codex/tests can navigate
    assert "===== BEGIN VERIFIED_RESULTS (scrubbed, id-free) =====" in p
    assert "===== BEGIN PROBLEM.md (verbatim goal) =====" in p


def test_scrub_no_ids_no_author_no_predecessors_no_frontmatter():
    with temp_project() as pdir:
        p = assemble.build_prompt(pdir)
    # ISOLATION: none of the fact frontmatter fields may reach the writer.
    assert "fact_id:" not in p, "fact_id frontmatter must be stripped"
    assert "author:" not in p, "author frontmatter must be stripped"
    assert "predecessors" not in p, "predecessors must never reach the writer"
    assert "problem_id:" not in p
    assert "glossary_introduces" not in p
    assert "external_refs" not in p
    # no fact slug / id anywhere (the example fact files are named fact_*.md)
    assert "fact_odd_sum_main" not in p
    assert "fact_square_recurrence" not in p
    assert "fact_odd_recurrence" not in p


def test_report_language_directive():
    # default narrative language is English
    with temp_project() as pdir:
        assert "Report language: English" in assemble.build_prompt(pdir)
    # an explicit language is passed through to the isolated writer, and the
    # register rule (math terminology stays English) is stated alongside it
    with temp_project() as pdir:
        p = assemble.build_prompt(pdir, language="Chinese")
        assert "Report language: Chinese" in p
        assert "terminology in English" in p


def test_empty_fact_graph_bundle_sentinel():
    # a project whose fact graph has no facts -> the sentinel note (assemble.py:145);
    # _ordered_load_bearing returns [] on empty (assemble.py:115).
    with temp_project() as pdir:
        facts = Path(pdir) / "fact_graph" / "facts"
        for f in facts.glob("*.md"):
            f.unlink()
        assert assemble.fact_bundle(pdir).strip().startswith("_(no verified results")
        # the empty bundle still yields a well-formed prompt (PROBLEM.md + writer prompt)
        p = assemble.build_prompt(pdir)
        assert "no verified results" in p


def test_ordered_load_bearing_cycle_is_tolerated():
    # a (should-not-happen) predecessor cycle must not hang: the cycle branch
    # (assemble.py:129) sorts the remaining nodes deterministically.
    class _CyclicFG:
        def list(self):
            return ["a", "b"]

        def predecessors(self, fid):
            return {"a": ["b"], "b": ["a"]}[fid]  # mutual cycle

    ordered = assemble._ordered_load_bearing(_CyclicFG())
    assert sorted(ordered) == ["a", "b"] and len(ordered) == 2


def test_ordered_load_bearing_empty_returns_empty():
    class _EmptyFG:
        def list(self):
            return []

        def predecessors(self, fid):
            return []

    assert assemble._ordered_load_bearing(_EmptyFG()) == []


def test_missing_required_file_raises():
    # missing writer prompt → raise (point the skill dir at an empty dir)
    with temp_project() as pdir, env(DANUS_HUMAN_SUMMARY_SKILL_DIR=str(pdir)):
        try:
            assemble.build_prompt(pdir)
            assert False, "missing writer prompt should raise"
        except FileNotFoundError:
            pass
    # missing project PROBLEM.md → raise
    with temp_project() as pdir:
        (pdir / "PROBLEM.md").unlink()
        try:
            assemble.build_prompt(pdir)
            assert False, "missing PROBLEM.md should raise"
        except FileNotFoundError:
            pass


def main() -> None:
    test_embeds_writer_prompt_problem_and_proof_verbatim()
    print("  [ok] assemble embeds writer prompt + PROBLEM.md + fact proof text (verbatim)")
    test_scrub_no_ids_no_author_no_predecessors_no_frontmatter()
    print("  [ok] scrub: NO fact_id / author: / predecessors / frontmatter / slug reaches the writer")
    test_report_language_directive()
    print("  [ok] report-language directive (default English; explicit language passed through)")
    test_empty_fact_graph_bundle_sentinel()
    print("  [ok] empty fact graph -> 'no verified results' sentinel + well-formed prompt")
    test_ordered_load_bearing_cycle_is_tolerated()
    print("  [ok] predecessor cycle tolerated (deterministic, no hang)")
    test_ordered_load_bearing_empty_returns_empty()
    print("  [ok] empty fact graph -> _ordered_load_bearing returns []")
    test_missing_required_file_raises()
    print("  [ok] missing writer prompt or PROBLEM.md raises")
    print("ALL ASSEMBLE TESTS PASSED")


if __name__ == "__main__":
    main()
