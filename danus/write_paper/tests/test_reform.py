"""Offline tests for the write-paper design reform (target-closure scoping,
brief-named structural exemplar, and the shared ledger closure). Zero network /
codex.

Covers:
  - resolve_headline precedence: arg > brief > TARGET.md > unset (no guess);
  - the DEFAULT is the target CLOSURE (on-path facts), not all facts — a
    proven-but-unused SIDE lemma is excluded from the writer content;
  - the reference ledger is seeded from the SAME closure (side-lemma refs excluded);
  - the brief-named structural exemplar is embedded (and none when unset);
  - the unset target REFUSES (TargetUnsetError), never guesses.

Runs standalone (``python -m danus.write_paper.tests.test_reform``) and pytest.
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

from danus.core import FactGraph
from danus.write_paper import assemble

from ._fixtures import MAIN_SKILL_DIR, SKILL_DIR, env, temp_project, seed_ledger_text


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

def _seed_ledger_mod():
    path = MAIN_SKILL_DIR / "driver" / "seed_ledger.py"
    spec = importlib.util.spec_from_file_location("_wp_seed_ledger_reform", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _add_side_lemma(pdir: Path) -> str:
    """Add a proven-but-UNUSED side lemma to the example graph: it is nothing's
    predecessor (so it is itself a terminal) but the headline target
    ``fact_odd_sum_main`` does not depend on it — so it is OFF the target closure.
    It carries a unique external_ref so we can detect ledger leakage. Returns the
    marker string that appears only in its proof body."""
    fg = FactGraph(pdir)
    marker = "SIDE LEMMA proof body marker zzz"
    # a fact with a fresh id (facts are content-addressed); no predecessors, so it
    # is a leaf; nothing depends on it, so it is also terminal-but-off-closure.
    fid = fg.add(
        problem_id="odd-sum",
        author="example-worker",
        statement="An unrelated side lemma with its own citation.",
        proof=marker,
        predecessors=[],
        external_refs=[{"key": "Side99", "authors": ["S. Ide"],
                        "title": "An unrelated result", "year": "1999",
                        "cited_for": "an unrelated fact"}],
    )
    # rename the file to a readable fact_ slug so it is recognizably a fact and the
    # terminal-inference sorts deterministically alongside the example facts.
    src = pdir / "fact_graph" / "facts" / f"{fid}.md"
    dst = pdir / "fact_graph" / "facts" / "fact_side_lemma.md"
    raw = src.read_text(encoding="utf-8").replace(f"fact_id: {fid}", "fact_id: fact_side_lemma")
    dst.write_text(raw, encoding="utf-8")
    src.unlink()
    return marker


# --------------------------------------------------------------------------- #
# resolve_headline precedence                                                 #
# --------------------------------------------------------------------------- #

def test_resolve_headline_arg_wins():
    with temp_project() as pdir:
        ids, source = assemble.resolve_headline(pdir, ["fact_square_recurrence"])
        assert ids == ["fact_square_recurrence"] and source == "arg"


def test_resolve_headline_reads_brief_when_no_arg():
    # the example brief names headline_fact_ids: fact_odd_sum_main
    with temp_project() as pdir:
        ids, source = assemble.resolve_headline(pdir, None)
        assert ids == ["fact_odd_sum_main"] and source == "brief"


def _blank_brief_headline(pdir: Path) -> None:
    brief = Path(pdir) / "paper" / "PROJECT_BRIEF.md"
    brief.write_text(
        brief.read_text(encoding="utf-8").replace(
            "headline_fact_ids: fact_odd_sum_main", "headline_fact_ids:"),
        encoding="utf-8")


def test_resolve_headline_reads_target_md_when_brief_blank():
    # blank the brief field -> resolve from the finalized <project>/TARGET.md.
    with temp_project() as pdir:
        _blank_brief_headline(pdir)
        assemble.write_target_fact_ids(pdir, ["fact_odd_sum_main"])
        ids, source = assemble.resolve_headline(pdir, None)
        assert ids == ["fact_odd_sum_main"] and source == "target"


def test_resolve_headline_unset_refuses_no_guess():
    # blank brief AND no TARGET.md -> unset (no auto-infer / guess).
    with temp_project() as pdir:
        _blank_brief_headline(pdir)
        ids, source = assemble.resolve_headline(pdir, None)
        assert ids == [] and source == "unset", "an unset target must not be guessed"
        # fact_graph_content refuses rather than embedding all facts
        try:
            assemble.fact_graph_content(pdir)
            assert False, "unset target must raise TargetUnsetError, not embed all facts"
        except assemble.TargetUnsetError:
            pass


def test_terminal_facts_is_finalize_suggestion_helper():
    # _terminal_facts stays only as the finalize SUGGESTION helper (not a resolve
    # fallback): in the example only fact_odd_sum_main is terminal.
    with temp_project() as pdir:
        term = assemble._terminal_facts(FactGraph(Path(pdir)))
        assert term == ["fact_odd_sum_main"]  # the two leaves are predecessors of it


# --------------------------------------------------------------------------- #
# DEFAULT = target closure (on-path), not all facts                           #
# --------------------------------------------------------------------------- #

def test_default_content_is_closure_not_all_facts():
    # add an off-closure side lemma; the DEFAULT writer content (no headline) must
    # embed only the target closure and EXCLUDE the side lemma.
    with temp_project() as pdir:
        marker = _add_side_lemma(pdir)
        content = assemble.fact_graph_content(pdir)  # default -> brief headline closure
        assert "We argue by induction on $n$" in content      # target proof present
        assert "one-step telescoping relation" in content     # predecessor present
        assert marker not in content, "off-closure side lemma must be excluded from the default"


def test_writer_prompt_default_excludes_off_closure_lemma():
    with temp_project() as pdir:
        marker = _add_side_lemma(pdir)
        p = assemble.build_prompt("writer", pdir)  # no headline -> closure
        assert "We argue by induction on $n$" in p
        assert marker not in p


def test_explicit_headline_leaf_excludes_the_other_branch():
    with temp_project() as pdir:
        _add_side_lemma(pdir)
        content = assemble.fact_graph_content(pdir, headline=["fact_square_recurrence"])
        assert "The perfect squares grow by the consecutive odd numbers" in content
        assert "We argue by induction on $n$" not in content   # target excluded
        assert "one-step telescoping relation" not in content  # sibling excluded


# --------------------------------------------------------------------------- #
# ledger seeded from the SAME closure                                         #
# --------------------------------------------------------------------------- #

def test_ledger_scoped_to_closure_excludes_side_lemma_ref():
    mod = _seed_ledger_mod()
    with temp_project() as pdir:
        _add_side_lemma(pdir)
        # default (closure) seeding: the closure is fact_odd_sum_main + its two
        # predecessors, whose refs are AC24 (odd_recurrence) and Exm20 (main).
        ledger = mod.render(mod.collect(Path(pdir)))
        assert "AC24" in ledger and "Exm20" in ledger
        assert "Side99" not in ledger, "off-closure side-lemma ref must not appear in the ledger"


def test_ledger_all_facts_flag_restores_side_lemma_ref():
    mod = _seed_ledger_mod()
    with temp_project() as pdir:
        _add_side_lemma(pdir)
        ledger_all = mod.render(mod.collect(Path(pdir), all_facts=True))
        assert "Side99" in ledger_all, "--all-facts restores the legacy all-facts seeding"


def test_ledger_and_writer_share_one_closure():
    # the ledger's cited_by facts are exactly the writer's closure facts.
    mod = _seed_ledger_mod()
    with temp_project() as pdir:
        _add_side_lemma(pdir)
        closure = set(mod.closure_fact_ids(Path(pdir)))
        assert closure == {"fact_odd_sum_main", "fact_odd_recurrence", "fact_square_recurrence"}
        assert "fact_side_lemma" not in closure


def test_ledger_headline_arg_scopes_to_a_single_leaf():
    mod = _seed_ledger_mod()
    with temp_project() as pdir:
        _add_side_lemma(pdir)
        # headline = odd_recurrence only (a leaf with the AC24 ref); closure = {itself}
        ledger = mod.render(mod.collect(Path(pdir), headline=["fact_odd_recurrence"]))
        assert "AC24" in ledger
        assert "Exm20" not in ledger and "Side99" not in ledger


# --------------------------------------------------------------------------- #
# brief-named structural exemplar                                             #
# --------------------------------------------------------------------------- #

def test_structural_exemplar_none_when_brief_blank():
    with temp_project() as pdir:
        assert assemble.brief_structural_exemplar(pdir) is None
        p = assemble.build_prompt("writer", pdir)
        # the section delimiter is unique to an actually-embedded exemplar (the
        # role prompt text mentions the field name, so key on the BEGIN delimiter).
        assert "===== BEGIN STRUCTURAL_EXEMPLAR" not in p


def test_structural_exemplar_embedded_when_brief_names_existing_anchor():
    with tempfile.TemporaryDirectory() as sd:
        skill = Path(sd)
        shutil.copytree(SKILL_DIR, skill, dirs_exist_ok=True)
        adir = skill / "style" / "anchors" / "houseX"
        adir.mkdir(parents=True)
        (adir / "main.tex").write_text("\\section{HouseX skeleton}\n", encoding="utf-8")
        with env(DANUS_WRITE_PAPER_SKILL_DIR=str(skill)):
            with temp_project() as pdir:
                brief = Path(pdir) / "paper" / "PROJECT_BRIEF.md"
                brief.write_text(
                    brief.read_text(encoding="utf-8").replace(
                        "structural_exemplar:", "structural_exemplar: houseX"),
                    encoding="utf-8")
                assert assemble.brief_structural_exemplar(pdir) == "houseX"
                p = assemble.build_prompt("writer", pdir)
                assert "===== BEGIN STRUCTURAL_EXEMPLAR (houseX) =====" in p
                assert "HouseX skeleton" in p


def test_structural_exemplar_named_but_missing_is_dropped():
    # the brief names an anchor that does not exist -> no section (assemble drops it)
    with temp_project() as pdir:
        brief = Path(pdir) / "paper" / "PROJECT_BRIEF.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "structural_exemplar:", "structural_exemplar: ghost_anchor"),
            encoding="utf-8")
        assert assemble.brief_structural_exemplar(pdir) == "ghost_anchor"
        p = assemble.build_prompt("writer", pdir)
        assert "===== BEGIN STRUCTURAL_EXEMPLAR" not in p


def test_brief_headline_ignores_template_placeholder():
    # a brief still holding the angle-bracket template value yields no ids
    with temp_project() as pdir:
        brief = Path(pdir) / "paper" / "PROJECT_BRIEF.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "headline_fact_ids: fact_odd_sum_main",
                "headline_fact_ids: <fact ids here>"),
            encoding="utf-8")
        assert assemble.brief_headline_fact_ids(pdir) == []
        # -> no TARGET.md either -> unset (refuse, never guess)
        ids, source = assemble.resolve_headline(pdir, None)
        assert ids == [] and source == "unset"
        # but a finalized TARGET.md then resolves it
        assemble.write_target_fact_ids(pdir, ["fact_odd_sum_main"])
        ids, source = assemble.resolve_headline(pdir, None)
        assert ids == ["fact_odd_sum_main"] and source == "target"


def test_target_fact_ids_reader_formats():
    # the TARGET.md reader: absent -> []; one-id-per-line; comments/labels ignored;
    # only fact_ tokens kept.
    with temp_project() as pdir:
        assert assemble.target_fact_ids(pdir) == []              # absent -> []
        (Path(pdir) / "TARGET.md").write_text(
            "# a comment header\n\nfact_odd_sum_main\nfact_odd_recurrence\n",
            encoding="utf-8")
        assert assemble.target_fact_ids(pdir) == ["fact_odd_sum_main", "fact_odd_recurrence"]
        # a label line with inline ids + stray prose is parsed for fact_ tokens
        (Path(pdir) / "TARGET.md").write_text(
            "target_fact_ids: fact_odd_sum_main, not_a_fact\n", encoding="utf-8")
        assert assemble.target_fact_ids(pdir) == ["fact_odd_sum_main"]
        # blank file -> []
        (Path(pdir) / "TARGET.md").write_text("\n\n# only comments\n", encoding="utf-8")
        assert assemble.target_fact_ids(pdir) == []


def main() -> None:
    test_resolve_headline_arg_wins()
    print("  [ok] resolve_headline: explicit arg wins (source=arg)")
    test_resolve_headline_reads_brief_when_no_arg()
    print("  [ok] resolve_headline: reads brief headline_fact_ids when no arg (source=brief)")
    test_resolve_headline_reads_target_md_when_brief_blank()
    print("  [ok] resolve_headline: reads <project>/TARGET.md when brief blank (source=target)")
    test_resolve_headline_unset_refuses_no_guess()
    print("  [ok] resolve_headline: unset -> refuse (no guess); fact_graph_content raises")
    test_terminal_facts_is_finalize_suggestion_helper()
    print("  [ok] _terminal_facts is the finalize suggestion helper (not a resolve fallback)")
    test_target_fact_ids_reader_formats()
    print("  [ok] target_fact_ids reader: absent/one-per-line/label/comments")
    test_default_content_is_closure_not_all_facts()
    print("  [ok] DEFAULT fact content = target closure, off-closure side lemma excluded")
    test_writer_prompt_default_excludes_off_closure_lemma()
    print("  [ok] writer prompt default excludes the off-closure side lemma")
    test_explicit_headline_leaf_excludes_the_other_branch()
    print("  [ok] explicit single-leaf headline excludes the other branch")
    test_ledger_scoped_to_closure_excludes_side_lemma_ref()
    print("  [ok] ledger scoped to closure: off-closure side-lemma ref excluded")
    test_ledger_all_facts_flag_restores_side_lemma_ref()
    print("  [ok] ledger --all-facts restores legacy all-facts seeding")
    test_ledger_and_writer_share_one_closure()
    print("  [ok] ledger closure == writer closure (one shared closure)")
    test_ledger_headline_arg_scopes_to_a_single_leaf()
    print("  [ok] ledger --headline scopes to a single leaf's closure")
    test_structural_exemplar_none_when_brief_blank()
    print("  [ok] no structural exemplar section when the brief names none")
    test_structural_exemplar_embedded_when_brief_names_existing_anchor()
    print("  [ok] brief-named structural exemplar embedded deterministically")
    test_structural_exemplar_named_but_missing_is_dropped()
    print("  [ok] brief names a missing anchor -> section dropped")
    test_brief_headline_ignores_template_placeholder()
    print("  [ok] template placeholder headline ignored -> unset, then TARGET.md resolves")
    print("ALL REFORM TESTS PASSED")


if __name__ == "__main__":
    main()
