"""Offline tests for the main-agent CURATION seam (P0 redesign):

  * ``assemble.subgraph_skeleton`` — the compact, deterministic closure skeleton the
    main agent reads to SELECT a load-bearing subset (statements only, no codex);
  * ``assemble.selected_partition`` — split a selection into (present-in-full,
    referenced-as-statements);
  * ``assemble.build_writer_prompt`` — the SELECTED_FACTS / REFERENCED_FACTS /
    MAIN_AGENT_INSTRUCTIONS shape when a selection is passed;
  * ``server.paper_subgraph`` — the read-only MCP tool (needs_target refusal, ok);
  * ``server.paper_write`` with ``fact_ids`` / ``instructions`` — single-pass
    selection path, backward-compat when omitted, ``bad_fact_ids`` refusal.

All codex is faked (a capturing stub) so nothing hits the network. The example
project's closure is exactly three facts: ``fact_odd_sum_main`` (target) with
predecessors ``fact_odd_recurrence`` + ``fact_square_recurrence``.

Runs under pytest and standalone (``python -m danus.write_paper.tests.test_subgraph``).
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path

from danus.write_paper import assemble, server

from ._fixtures import env, temp_project

_TARGET = "fact_odd_sum_main"
_PREDS = {"fact_odd_recurrence", "fact_square_recurrence"}
# a proof-ONLY phrase from fact_odd_recurrence (absent when it is referenced-only,
# i.e. embedded as a statement without its proof).
_RECURRENCE_PROOF_PHRASE = "one-step telescoping relation between consecutive partial sums"

_GOOD_TEX = (
    "\\documentclass{amsart}\n\\begin{document}\n\\title{T}\n\\maketitle\n"
    "We prove $S(n)=n^2$.\n\\end{document}\n"
)


@contextmanager
def _capture_codex(stdout=_GOOD_TEX, returncode=0):
    """Fake ``server.driver.run_codex`` capturing the prompts it is driven with in
    ``.prompts`` (so a test can assert what the tool assembled)."""
    orig = server.driver.run_codex
    state = {"prompts": []}

    def fake(prompt, *, model, effort, timeout=0, networked=False, gateway_role="verifier"):
        state["prompts"].append(prompt)
        return subprocess.CompletedProcess(args=["fake"], returncode=returncode,
                                           stdout=stdout, stderr="")

    server.driver.run_codex = fake
    try:
        yield state
    finally:
        server.driver.run_codex = orig


def _blank_brief_headline(pdir: Path) -> None:
    brief = pdir / "paper" / "PROJECT_BRIEF.md"
    brief.write_text(
        brief.read_text(encoding="utf-8").replace(
            "headline_fact_ids: fact_odd_sum_main", "headline_fact_ids:"),
        encoding="utf-8")


# --------------------------------------------------------------------------- #
# subgraph_skeleton (assemble, pure)                                           #
# --------------------------------------------------------------------------- #

def test_subgraph_skeleton_shape_order_and_degrees():
    with temp_project() as pdir:
        skel = assemble.subgraph_skeleton(pdir, [_TARGET])
        assert skel["count"] == 3
        facts = skel["facts"]
        ids = [f["id"] for f in facts]
        # topological order: predecessors precede the target (target is last)
        assert ids[-1] == _TARGET
        assert set(ids[:-1]) == _PREDS
        # every record carries the compact fields
        for f in facts:
            assert set(f) == {"id", "statement", "predecessors", "dependents",
                              "glossary_introduces"}
            assert f["statement"], f  # non-empty one-liner
        by_id = {f["id"]: f for f in facts}
        # both predecessors are load-bearing (used by the target) -> in-degree 1
        assert by_id["fact_odd_recurrence"]["dependents"] == 1
        assert by_id["fact_square_recurrence"]["dependents"] == 1
        assert by_id[_TARGET]["dependents"] == 0
        # the target's predecessor DAG edges are reported
        assert set(by_id[_TARGET]["predecessors"]) == _PREDS
        # glossary term S(n) is introduced by fact_odd_recurrence
        assert "S(n)" in by_id["fact_odd_recurrence"]["glossary_introduces"]
        # statements only — no proof text leaks into the skeleton
        assert _RECURRENCE_PROOF_PHRASE not in by_id["fact_odd_recurrence"]["statement"]


def test_subgraph_skeleton_is_deterministic():
    with temp_project() as pdir:
        a = assemble.subgraph_skeleton(pdir, [_TARGET])
        b = assemble.subgraph_skeleton(pdir, [_TARGET])
        assert a == b


# --------------------------------------------------------------------------- #
# selected_partition (assemble, pure)                                          #
# --------------------------------------------------------------------------- #

def test_selected_partition_splits_present_and_referenced():
    with temp_project() as pdir:
        ordered_selected, referenced_ids = assemble.selected_partition(pdir, [_TARGET])
        assert ordered_selected == [_TARGET]
        assert set(referenced_ids) == _PREDS  # direct predecessors, not selected


def test_selected_partition_rejects_unknown_id():
    with temp_project() as pdir:
        try:
            assemble.selected_partition(pdir, ["fact_does_not_exist"])
            assert False, "expected ValueError on an unknown fact id"
        except ValueError as e:
            assert "fact_does_not_exist" in str(e)


# --------------------------------------------------------------------------- #
# build_writer_prompt selection shape (assemble, pure)                         #
# --------------------------------------------------------------------------- #

def test_writer_prompt_selection_embeds_only_selected_facts():
    with temp_project() as pdir:
        prompt = assemble.build_writer_prompt(
            pdir, headline=[_TARGET], fact_ids=[_TARGET],
            instructions="Present the main theorem in a single section.")
        # curation gives the writer ONLY the selected important facts (in full) +
        # the instructions block — NO "referenced-as-unproved-lemmas" section (that
        # dangling was the defect) and NOT the legacy whole-closure section.
        assert "===== BEGIN SELECTED_FACTS" in prompt
        assert "===== BEGIN MAIN_AGENT_INSTRUCTIONS" in prompt
        assert "Present the main theorem in a single section." in prompt
        assert "===== BEGIN REFERENCED_FACTS" not in prompt
        assert "===== BEGIN FACT_GRAPH_CONTENT" not in prompt
        # the selected fact's FULL body is embedded verbatim
        ordered_selected, _ = assemble.selected_partition(pdir, [_TARGET])
        assert assemble.full_bodies_for(pdir, ordered_selected).strip() in prompt
        # a NON-selected predecessor's proof is NOT dumped in (writer inlines/glosses)
        assert _RECURRENCE_PROOF_PHRASE not in prompt


def test_writer_prompt_no_selection_is_legacy_closure():
    with temp_project() as pdir:
        prompt = assemble.build_writer_prompt(pdir, headline=[_TARGET])
        assert "===== BEGIN FACT_GRAPH_CONTENT" in prompt
        assert "===== BEGIN SELECTED_FACTS" not in prompt
        assert "===== BEGIN MAIN_AGENT_INSTRUCTIONS" not in prompt
        # the whole closure is present in full -> the predecessor proof IS embedded
        assert _RECURRENCE_PROOF_PHRASE in prompt


# --------------------------------------------------------------------------- #
# server.paper_subgraph (MCP tool)                                            #
# --------------------------------------------------------------------------- #

def test_paper_subgraph_tool_ok_resolves_from_brief():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        out = server.paper_subgraph()
        assert out["status"] == "ok"
        assert out["headline"] == [_TARGET]
        assert out["headline_source"] == "brief"
        assert out["count"] == 3
        assert {f["id"] for f in out["facts"]} == {_TARGET} | _PREDS


def test_paper_subgraph_tool_needs_target_when_unset():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        _blank_brief_headline(pdir)
        out = server.paper_subgraph()
        assert out["status"] == "needs_target"
        assert out["headline_source"] == "unset" and out["facts"] == []
        assert out["candidates"] == [_TARGET]


def test_paper_subgraph_tool_is_registered():
    assert "paper_subgraph" in server._TOOLS


# --------------------------------------------------------------------------- #
# server.paper_write with fact_ids / instructions                             #
# --------------------------------------------------------------------------- #

def test_paper_write_selection_single_pass_drives_curated_prompt():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        with _capture_codex() as cap:
            out = server.paper_write(fact_ids=[_TARGET],
                                     instructions="One section only.")
        assert out["status"] == "ok"
        assert out["selected_facts"] == 1
        assert out["fact_id_warnings"] == []
        assert Path(out["tex_path"]).read_text(encoding="utf-8") == _GOOD_TEX
        # the driven prompt was the CURATED prompt, not the whole closure
        prompt = cap["prompts"][0]
        assert "===== BEGIN SELECTED_FACTS" in prompt
        assert "===== BEGIN MAIN_AGENT_INSTRUCTIONS" in prompt
        assert "One section only." in prompt
        assert _RECURRENCE_PROOF_PHRASE not in prompt  # predecessor is referenced-only


def test_paper_write_bad_fact_ids_refuses_no_paper():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        with _capture_codex():
            out = server.paper_write(fact_ids=["fact_bogus", _TARGET])
        assert out["status"] == "bad_fact_ids"
        assert out["unknown_fact_ids"] == ["fact_bogus"]
        assert not Path(out["tex_path"]).exists()


def test_paper_write_out_of_closure_id_warns_but_writes():
    # fact_square_recurrence IS in the closure; to exercise the warning we select the
    # target plus a valid fact that is NOT in the target's closure would require a
    # second terminal — instead select an explicit headline whose closure excludes a
    # chosen fact. Here: headline=fact_odd_recurrence (closure = itself), select the
    # main fact too -> main is outside that closure -> warning, but paper still writes.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        with _capture_codex():
            out = server.paper_write(headline=["fact_odd_recurrence"],
                                     fact_ids=["fact_odd_recurrence", _TARGET])
        assert out["status"] == "ok"
        assert out["fact_id_warnings"] and "outside the target closure" in out["fact_id_warnings"][0]


def test_paper_write_no_selection_backward_compatible():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        with _capture_codex() as cap:
            out = server.paper_write()
        assert out["status"] == "ok"
        assert out["selected_facts"] == 0
        assert "===== BEGIN FACT_GRAPH_CONTENT" in cap["prompts"][0]
        assert "===== BEGIN SELECTED_FACTS" not in cap["prompts"][0]


# --------------------------------------------------------------------------- #
# standalone runner                                                            #
# --------------------------------------------------------------------------- #

def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS ({len(fns)} subgraph/selection tests)")


if __name__ == "__main__":
    _run_all()
