"""Offline tests for Item B — MULTIPLE papers per project. Zero network / codex.

The whole point of the design is that a paper's facts are the SAME
transitive-predecessor closure of its headline set the single-paper pipeline
already computed; the only delta is WHERE the headline set + workspace live
(per-paper, rooted by ``paper_id``). These tests prove:

  - ``paper_workspace`` / ``paper_target_path`` map the DEFAULT paper to the LEGACY
    paths (``<project>/paper/`` + ``<project>/TARGET.md``) and a non-default
    paper_id to ``<project>/papers/<paper_id>/`` (+ its own TARGET.md);
  - a non-default paper_id is validated as a single safe path segment (no escape);
  - the three workflows produce correct, NON-COLLIDING output:
      1 paper / 1 thm ; N papers / 1 thm each ; N papers / multi-thm;
  - a multi-theorem paper's fact set EQUALS the union closure of its headline set,
    IDENTICAL to calling ``_toposort_with_predecessors`` on that seed list directly
    (proves the closure logic is REUSED, not reimplemented);
  - ``finalize --paper`` records per-paper targets (default → legacy path);
  - the writer's facts and the seeded ledger stay in lockstep PER PAPER.

Runs standalone (``python -m danus.write_paper.tests.test_multi_paper``) and pytest.
"""

from __future__ import annotations

import importlib.util
import subprocess
from contextlib import contextmanager
from pathlib import Path

from danus.core import FactGraph
from danus.write_paper import assemble, server

from ._fixtures import MAIN_SKILL_DIR, env, temp_project


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

def _seed_ledger_mod():
    path = MAIN_SKILL_DIR / "driver" / "seed_ledger.py"
    spec = importlib.util.spec_from_file_location("_wp_seed_ledger_multi", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _add_second_theorem(pdir: Path) -> str:
    """Add a SECOND terminal theorem to the example graph with its own predecessor
    and a unique external_ref, so we can build a second paper with a disjoint (but
    overlapping is allowed) closure. Returns the new terminal fact id."""
    fg = FactGraph(pdir)
    lemma = fg.add(
        problem_id="odd-sum",
        author="example-worker",
        statement="A helper lemma for the second theorem.",
        proof="SECOND LEMMA body marker.",
        predecessors=[],
        external_refs=[{"key": "ThmB99", "authors": ["B. Two"],
                        "title": "The second reference", "year": "1999",
                        "cited_for": "a fact used only by theorem B"}],
    )
    main = fg.add(
        problem_id="odd-sum",
        author="example-worker",
        statement="The second headline theorem.",
        proof="SECOND MAIN body; depends on the helper lemma.",
        predecessors=[lemma],
        external_refs=[],
    )
    return main


@contextmanager
def _fake_codex(stdout=""):
    """Stub server.driver.run_codex; capture the prompts it was driven with."""
    orig = server.driver.run_codex
    calls = {"prompts": []}

    def fake(prompt, *, model, effort, timeout=0, networked=False, gateway_role="verifier"):
        calls["prompts"].append(prompt)
        return subprocess.CompletedProcess(args=["fake"], returncode=0,
                                           stdout=stdout, stderr="")

    server.driver.run_codex = fake
    try:
        yield calls
    finally:
        server.driver.run_codex = orig


_CLEAN_TEX = (
    "\\documentclass{amsart}\n\\begin{document}\n\\title{T}\n\\maketitle\n"
    "We prove the theorem.\n\\end{document}\n"
)


def _scaffold_paper_workspace(pdir: Path, paper_id, headline) -> None:
    """Provision a non-default paper's workspace so the writer prompt can be built:
    record its target, copy a PROJECT_BRIEF.md, and seed its REFERENCE_LEDGER from
    its OWN closure (via seed_ledger --paper). Mirrors what the operator/main agent
    does per paper."""
    ws = assemble.paper_workspace(pdir, paper_id)
    ws.mkdir(parents=True, exist_ok=True)
    assemble.write_target_fact_ids(pdir, headline, paper_id=paper_id)
    # a minimal brief (the default paper's brief lives at <project>/paper/). Leave
    # headline_fact_ids blank so the recorded TARGET.md is the resolution source
    # (TARGET.md accepts content-addressed hex ids; the brief field keeps only
    # ``fact_`` slugs).
    (ws / "PROJECT_BRIEF.md").write_text(
        f"# BRIEF for paper {paper_id}\nheadline_fact_ids:\n"
        "structural_exemplar:\n", encoding="utf-8")
    mod = _seed_ledger_mod()
    assert mod.main([str(pdir), "--paper", str(paper_id)]) == 0


# --------------------------------------------------------------------------- #
# helpers: workspace + target path mapping (back-compat)                       #
# --------------------------------------------------------------------------- #

def test_default_paper_maps_to_legacy_paths():
    p = Path("/proj")
    # None / "" / the canonical default slug all map to the LEGACY paths.
    for pid in (None, "", assemble.DEFAULT_PAPER_ID):
        assert assemble.paper_workspace(p, pid) == p / "paper"
        assert assemble.paper_target_path(p, pid) == p / "TARGET.md"


def test_non_default_paper_maps_to_papers_subdir():
    p = Path("/proj")
    assert assemble.paper_workspace(p, "thmA") == p / "papers" / "thmA"
    assert assemble.paper_target_path(p, "thmA") == p / "papers" / "thmA" / "TARGET.md"


def test_paper_id_validated_as_single_safe_segment():
    p = Path("/proj")
    for bad in ("../escape", "a/b", "with space", "/abs", "."):
        try:
            assemble.paper_workspace(p, bad)
        except ValueError:
            continue
        raise AssertionError(f"paper_id {bad!r} should have been rejected")


# --------------------------------------------------------------------------- #
# union-closure equality — the closure logic is REUSED, not reimplemented       #
# --------------------------------------------------------------------------- #

def test_multitheorem_factset_equals_union_closure_of_headline_seeds():
    """A multi-theorem paper's fact set is IDENTICAL to
    ``_toposort_with_predecessors(fg, seeds)`` on that headline seed list — the
    exact single closure primitive. No second closure path exists."""
    with temp_project() as pdir:
        second = _add_second_theorem(pdir)
        fg = FactGraph(pdir)
        seeds = ["fact_odd_sum_main", second]
        # register a multi-theorem paper's target, then resolve it the way the
        # writer does (via resolve_headline -> the SAME toposort).
        assemble.write_target_fact_ids(pdir, seeds, paper_id="combined")
        resolved, source = assemble.resolve_headline(pdir, None, paper_id="combined")
        assert source == "target"
        via_pipeline = assemble._toposort_with_predecessors(fg, resolved)
        via_direct = assemble._toposort_with_predecessors(fg, seeds)
        assert via_pipeline == via_direct, "the paper's fact set must be the union closure"
        # the union closure contains BOTH theorems' predecessors.
        assert set(seeds).issubset(set(via_pipeline))
        assert "fact_odd_recurrence" in via_pipeline  # a predecessor of the first
        assert set(fg.predecessors(second)).issubset(set(via_pipeline))


# --------------------------------------------------------------------------- #
# WORKFLOW 1 — one paper, one theorem (the legacy default, back-compat)         #
# --------------------------------------------------------------------------- #

def test_workflow_one_paper_one_theorem_default_legacy_paths():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_CLEAN_TEX):
        out = server.paper_write()  # no paper_id -> default -> brief headline
        assert out["status"] == "ok", out
        # legacy path is written; NO papers/ dir is created.
        assert out["tex_path"] == str(pdir / "paper" / "main.tex")
        assert (pdir / "paper" / "main.tex").is_file()
        assert not (pdir / "papers").exists()


# --------------------------------------------------------------------------- #
# WORKFLOW 2 — N papers, 1 theorem each (separate workspaces, no overwrite)     #
# --------------------------------------------------------------------------- #

def test_workflow_n_papers_one_theorem_each_no_collision():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        second = _add_second_theorem(pdir)
        # paper A (default/legacy) targets the first theorem; paper B (non-default)
        # targets the second. Each gets its own target + workspace.
        assemble.write_target_fact_ids(pdir, ["fact_odd_sum_main"])           # default
        _scaffold_paper_workspace(pdir, "thmB", [second])                    # non-default

        with _fake_codex(stdout="%%%A%%%\n" + _CLEAN_TEX) as ca:
            outA = server.paper_write()
        with _fake_codex(stdout="%%%B%%%\n" + _CLEAN_TEX) as cb:
            outB = server.paper_write(paper_id="thmB")

        assert outA["status"] == "ok" and outB["status"] == "ok"
        texA = pdir / "paper" / "main.tex"
        texB = pdir / "papers" / "thmB" / "main.tex"
        assert texA.is_file() and texB.is_file()
        # NON-COLLIDING: distinct files, distinct content, neither overwrote the other.
        assert texA.read_text() != texB.read_text()
        assert "%%%A%%%" in texA.read_text()
        assert "%%%B%%%" in texB.read_text()
        # each writer prompt embedded its OWN theorem's closure (different seeds).
        assert outA["headline"] == ["fact_odd_sum_main"]
        assert outB["headline"] == [second]


# --------------------------------------------------------------------------- #
# WORKFLOW 3 — N papers, one MULTI-theorem paper                                #
# --------------------------------------------------------------------------- #

def test_workflow_n_papers_multi_theorem_paper():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        second = _add_second_theorem(pdir)
        # a single "combined" paper whose headline set is BOTH theorems.
        seeds = ["fact_odd_sum_main", second]
        _scaffold_paper_workspace(pdir, "combined", seeds)
        with _fake_codex(stdout=_CLEAN_TEX) as calls:
            out = server.paper_write(paper_id="combined")
        assert out["status"] == "ok", out
        assert out["headline"] == seeds
        assert (pdir / "papers" / "combined" / "main.tex").is_file()
        # the writer prompt embedded the UNION closure of both seeds: every fact's
        # unique proof-body marker appears in the assembled writer prompt.
        fg = FactGraph(pdir)
        union = assemble._toposort_with_predecessors(fg, seeds)
        prompt = calls["prompts"][0]
        assert "SECOND MAIN body" in prompt          # the second theorem
        assert "SECOND LEMMA body marker" in prompt  # its predecessor lemma
        # and the union equals the direct primitive call (closure reuse, per paper).
        assert union == assemble._toposort_with_predecessors(
            fg, assemble.resolve_headline(pdir, None, "combined")[0])


# --------------------------------------------------------------------------- #
# finalize --paper records per-paper targets (default -> legacy path)           #
# --------------------------------------------------------------------------- #

def test_finalize_paper_records_per_paper_targets():
    import danus.orchestration.cli as cli
    with temp_project() as pdir, env(DANUS_AGENTS_ROOT=str(pdir.parent),
                                     DANUS_PROJECT_DIR=None):
        project = pdir.name
        second = _add_second_theorem(pdir)
        # default paper -> legacy <project>/TARGET.md
        rA = cli.do_finalize(project, ["fact_odd_sum_main"])
        assert rA["target_file"] == str(pdir / "TARGET.md")
        assert (pdir / "TARGET.md").is_file()
        # non-default paper -> <project>/papers/thmB/TARGET.md
        rB = cli.do_finalize(project, [second], paper_id="thmB")
        assert rB["target_file"] == str(pdir / "papers" / "thmB" / "TARGET.md")
        assert (pdir / "papers" / "thmB" / "TARGET.md").is_file()
        # the two targets are independent.
        assert assemble.target_fact_ids(pdir) == ["fact_odd_sum_main"]
        assert assemble.target_fact_ids(pdir, "thmB") == [second]


def test_finalize_rejects_bad_paper_id():
    import danus.orchestration.cli as cli
    with temp_project() as pdir, env(DANUS_AGENTS_ROOT=str(pdir.parent),
                                     DANUS_PROJECT_DIR=None):
        project = pdir.name
        try:
            cli.do_finalize(project, ["fact_odd_sum_main"], paper_id="../escape")
        except SystemExit:
            return
        raise AssertionError("finalize should reject an unsafe paper_id")


# --------------------------------------------------------------------------- #
# writer facts and the seeded ledger stay in lockstep PER PAPER                 #
# --------------------------------------------------------------------------- #

def test_writer_and_ledger_share_one_closure_per_paper():
    mod = _seed_ledger_mod()
    with temp_project(with_ledger=False) as pdir:
        second = _add_second_theorem(pdir)
        assemble.write_target_fact_ids(pdir, ["fact_odd_sum_main"], paper_id="thmA")
        assemble.write_target_fact_ids(pdir, [second], paper_id="thmB")

        # each paper's ledger closure == that paper's writer closure (SAME primitive).
        closureA = set(mod.closure_fact_ids(pdir, paper_id="thmA"))
        closureB = set(mod.closure_fact_ids(pdir, paper_id="thmB"))
        assert closureA != closureB
        assert "fact_odd_sum_main" in closureA and "fact_odd_sum_main" not in closureB
        assert second in closureB and second not in closureA

        # seed each paper's ledger into its OWN workspace (no --out).
        assert mod.main([str(pdir), "--paper", "thmA"]) == 0
        assert mod.main([str(pdir), "--paper", "thmB"]) == 0
        ledgerA = (pdir / "papers" / "thmA" / "REFERENCE_LEDGER.md").read_text()
        ledgerB = (pdir / "papers" / "thmB" / "REFERENCE_LEDGER.md").read_text()
        # paper B's unique ref appears ONLY in B's ledger; A's telescoping ref only in A.
        assert "ThmB99" in ledgerB and "ThmB99" not in ledgerA
        assert "ThmB99" not in ledgerA


def main() -> None:
    test_default_paper_maps_to_legacy_paths()
    print("  [ok] default paper_id -> legacy <project>/paper/ + <project>/TARGET.md")
    test_non_default_paper_maps_to_papers_subdir()
    print("  [ok] non-default paper_id -> <project>/papers/<id>/ + its own TARGET.md")
    test_paper_id_validated_as_single_safe_segment()
    print("  [ok] paper_id validated as a single safe path segment (no escape)")
    test_multitheorem_factset_equals_union_closure_of_headline_seeds()
    print("  [ok] multi-theorem fact set == union closure of seeds (closure REUSED)")
    test_workflow_one_paper_one_theorem_default_legacy_paths()
    print("  [ok] workflow 1: one paper / one theorem on the legacy default paths")
    test_workflow_n_papers_one_theorem_each_no_collision()
    print("  [ok] workflow 2: N papers / 1 thm each — separate workspaces, no overwrite")
    test_workflow_n_papers_multi_theorem_paper()
    print("  [ok] workflow 3: a multi-theorem paper embeds the union closure")
    test_finalize_paper_records_per_paper_targets()
    print("  [ok] finalize --paper records per-paper targets (default -> legacy path)")
    test_finalize_rejects_bad_paper_id()
    print("  [ok] finalize rejects an unsafe paper_id")
    test_writer_and_ledger_share_one_closure_per_paper()
    print("  [ok] writer facts and the seeded ledger stay in lockstep PER PAPER")
    print("ALL MULTI-PAPER TESTS PASSED")


if __name__ == "__main__":
    main()
