"""Offline tests for CHUNKED paper generation — danus.write_paper.paper_chunked
and the server.paper_write chunked path.

All codex is faked (no network, no API). Covers:
  - THRESHOLD: a small closure uses single-pass (chunker NOT invoked); an
    over-budget closure (forced via a low DANUS_PAPER_WRITE_CHUNK_CHARS) chunks.
  - PLANNING: parse preamble/frontmatter/sections-JSON/bibliography; coverage passes
    when every fact is assigned, FAILS (honest, no main.tex) when one is unassigned.
  - PER-SECTION FILL + STITCH: each section body (+provenance) stitched into main.tex
    (preamble, every section, bibliography, \\end{document}); merged .provenance.json;
    leak-gate runs on the stitched whole (a leaked id in any section quarantines).
  - HONESTY: a section-writer non-ok → paper_write fails, no main.tex, phase reported,
    run-log written.

Runs standalone (``python -m danus.write_paper.tests.test_chunked``) and under pytest.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

from danus.write_paper import assemble, paper_chunked, server

from ._fixtures import env, temp_project


# --------------------------------------------------------------------------- #
# fake codex — a SCRIPTED sequence keyed by which phase prompt arrives         #
# --------------------------------------------------------------------------- #

@contextmanager
def _fake_codex_router(planner_out, section_outs, planner_rc=0, section_rc=0):
    """Route each fake codex call by the role marker in the prompt: the PLANNER
    prompt ('You are the PAPER PLANNER') returns ``planner_out``; each subsequent
    SECTION-WRITER prompt returns the next element of ``section_outs`` (a list, one
    per section, in call order). ``planner_rc`` / ``section_rc`` set the returncode.
    Captures the prompts in ``.prompts``."""
    orig = server.driver.run_codex
    state = {"prompts": [], "sec_i": 0}

    def fake(prompt, *, model, effort, timeout=0, networked=False, gateway_role="verifier"):
        state["prompts"].append(prompt)
        if "You are the PAPER PLANNER" in prompt:
            return subprocess.CompletedProcess(args=["fake"], returncode=planner_rc,
                                               stdout=planner_out, stderr="")
        # section writer
        i = state["sec_i"]
        state["sec_i"] += 1
        out = section_outs[i] if i < len(section_outs) else ""
        return subprocess.CompletedProcess(args=["fake"], returncode=section_rc,
                                           stdout=out, stderr="")

    server.driver.run_codex = fake
    try:
        yield state
    finally:
        server.driver.run_codex = orig


# The example project closure (deterministic; asserted in a threshold test below).
_CLOSURE = ["fact_odd_recurrence", "fact_square_recurrence", "fact_odd_sum_main"]

_PREAMBLE = (
    "\\documentclass{amsart}\n"
    "\\usepackage{amsmath,amsthm}\n"
    "\\DeclareMathOperator{\\odd}{odd}\n"
    "\\newtheorem{thm}{Theorem}\n"
)
_FRONTMATTER = (
    "\\begin{document}\n\\title{The Sum of the First $n$ Odd Numbers}\n"
    "\\author{\\textsf{[AUTHOR NAME]}}\n\\subjclass[2020]{11A25}\n"
    "\\keywords{odd numbers}\n\\date{}\n"
    "\\begin{abstract} We prove that $S(n)=n^2$. \\end{abstract}\n\\maketitle\n"
)
_BIB = (
    "\\begin{thebibliography}{99}\n"
    "\\bibitem[Exm20]{Exm20} C. Example, Elementary induction, revisited.\n"
    "\\end{thebibliography}\n"
)


def _planner_out(sections):
    """Assemble a planner stdout with the four separators. ``sections`` is the JSON
    array (python list) placed in the %%%SECTIONS%%% block."""
    return (
        f"{paper_chunked._SEP_PREAMBLE}\n{_PREAMBLE}"
        f"{paper_chunked._SEP_FRONTMATTER}\n{_FRONTMATTER}"
        f"{paper_chunked._SEP_SECTIONS}\n{json.dumps(sections)}\n"
        f"{paper_chunked._SEP_BIBLIOGRAPHY}\n{_BIB}"
    )


# a full coverage plan: intro (no facts) + one section carrying all closure facts.
_FULL_SECTIONS = [
    {"title": "Introduction", "label": "sec:intro", "fact_ids": []},
    {"title": "Main results", "label": "sec:main", "fact_ids": _CLOSURE},
]


def _section_body(label, title, prov=None, extra=""):
    """A section-writer stdout: a \\section body (+ optional %%%PROVENANCE%%% map)."""
    body = f"\\section{{{title}}}\\label{{{label}}}\nSome prose. {extra}\n"
    if prov is not None:
        body += f"{paper_chunked._SEP_PROVENANCE}\n{json.dumps(prov)}\n"
    return body


@contextmanager
def _no_engine():
    """Force the compile gate off — chunked path does not compile (single-pass
    doesn't either), so this is a no-op guard kept for symmetry / clarity."""
    yield


# --------------------------------------------------------------------------- #
# THRESHOLD                                                                     #
# --------------------------------------------------------------------------- #

def test_threshold_small_closure_uses_single_pass_not_chunker():
    # Under budget (the default 800K, or any budget above the ~62K single-pass
    # prompt) → the chunker is NOT invoked; the single-pass path runs unchanged.
    from danus.write_paper.tests.test_server import _fake_codex, _GOOD_TEX
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        over, n, budget = paper_chunked.should_chunk(pdir, _CLOSURE, None)
        assert over is False and n < budget
        out = server.paper_write()
        assert out["status"] == "ok"
        assert "chunked" not in out, "single-pass envelope has no chunked flag"


def test_threshold_over_budget_triggers_chunking():
    # A tiny budget forces chunking on the small stub project deterministically.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        over, n, budget = paper_chunked.should_chunk(pdir, _CLOSURE, None)
        assert over is True and budget == 100 and n > 100
        with _fake_codex_router(
                planner_out=_planner_out(_FULL_SECTIONS),
                section_outs=[_section_body("sec:intro", "Introduction"),
                              _section_body("sec:main", "Main results")]):
            out = server.paper_write()
        assert out["status"] == "ok"
        assert out["chunked"] is True
        assert out["sections"] == 2


# a selection-aware plan: the extreme fallback chunks the CURATED subset (only the
# target), never the referenced-only predecessors.
_TARGET = "fact_odd_sum_main"
_SELECTED_SECTIONS = [
    {"title": "Introduction", "label": "sec:intro", "fact_ids": []},
    {"title": "Main results", "label": "sec:main", "fact_ids": [_TARGET]},
]


def test_chunked_fallback_respects_fact_ids_selection():
    # With a main-agent selection, chunking (the extreme fallback) partitions EXACTLY
    # the selected subset for coverage, and every section still gets the referenced-
    # only predecessors as \ref statements. The planner's coverage set is the
    # selection (one fact), not the whole 3-fact closure.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        over, _n, _b = paper_chunked.should_chunk(
            pdir, [_TARGET], None, fact_ids=[_TARGET], instructions="one section")
        assert over is True
        with _fake_codex_router(
                planner_out=_planner_out(_SELECTED_SECTIONS),
                section_outs=[_section_body("sec:intro", "Introduction"),
                              _section_body("sec:main", "Main results")]) as state:
            out = server.paper_write(fact_ids=[_TARGET], instructions="one section")
        assert out["status"] == "ok" and out["chunked"] is True
        assert out["selected_facts"] == 1
        # the section-writer for sec:main got the referenced predecessors as OTHER
        # statements (context to \ref), even though they are NOT assigned to a section.
        main_prompt = next(p for p in state["prompts"]
                           if "You are the PAPER SECTION WRITER" in p and "sec:main" in p)
        assert "fact_odd_recurrence" in main_prompt or "fact_square_recurrence" in main_prompt



def test_section_ref_context_is_bounded_to_direct_predecessors():
    # A section embeds ONLY the statements it \refs (its facts' direct predecessors),
    # never the whole closure. Embedding all-other-closure statements per section
    # overflowed codex's input hard-limit on a deep closure (~470 facts → 1.4M chars).
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        order = assemble.closure_order(pdir, None, None)
        # the main result \refs its two direct predecessors — and nothing else.
        ctx = assemble.section_ref_context_ids(pdir, ["fact_odd_sum_main"], order)
        assert set(ctx) == {"fact_odd_recurrence", "fact_square_recurrence"}
        # ordered by the coverage order (predecessors first), for coherent reading.
        assert ctx == [f for f in order if f in set(ctx)]
        # a LEAF fact (no predecessors) needs NO \ref context — not the whole closure.
        assert assemble.section_ref_context_ids(pdir, ["fact_odd_recurrence"], order) == []
        # a section never lists its OWN facts as \ref context.
        both = assemble.section_ref_context_ids(
            pdir, ["fact_odd_sum_main", "fact_odd_recurrence"], order)
        assert "fact_odd_recurrence" not in both and both == ["fact_square_recurrence"]


# --------------------------------------------------------------------------- #
# PLANNING PASS                                                                 #
# --------------------------------------------------------------------------- #

def test_planner_output_parsed_into_four_blocks():
    blocks = paper_chunked._split_planner_output(_planner_out(_FULL_SECTIONS))
    assert "\\documentclass{amsart}" in blocks["preamble"]
    assert "\\begin{document}" in blocks["frontmatter"]
    assert "\\begin{thebibliography}" in blocks["bibliography"]
    secs = paper_chunked._parse_sections(blocks["sections"])
    assert [s["label"] for s in secs] == ["sec:intro", "sec:main"]


def test_planner_missing_separator_is_chunk_error():
    bad = _planner_out(_FULL_SECTIONS).replace(paper_chunked._SEP_SECTIONS, "%%%NOPE%%%")
    try:
        paper_chunked._split_planner_output(bad)
        assert False, "expected ChunkError on a missing separator"
    except paper_chunked.ChunkError as e:
        assert e.phase == "plan"


def test_coverage_passes_when_every_fact_assigned():
    # no exception when the plan assigns every closure fact exactly once
    paper_chunked.check_coverage(_FULL_SECTIONS, _CLOSURE)


def test_coverage_fails_when_a_fact_is_unassigned():
    partial = [
        {"title": "Introduction", "label": "sec:intro", "fact_ids": []},
        {"title": "Main", "label": "sec:main", "fact_ids": _CLOSURE[:2]},  # drop one
    ]
    try:
        paper_chunked.check_coverage(partial, _CLOSURE)
        assert False, "expected ChunkError on an unassigned closure fact"
    except paper_chunked.ChunkError as e:
        assert e.phase == "plan"
        assert _CLOSURE[2] in str(e)


def test_coverage_fails_on_duplicate_assignment():
    dup = [
        {"title": "A", "label": "sec:a", "fact_ids": _CLOSURE},
        {"title": "B", "label": "sec:b", "fact_ids": [_CLOSURE[0]]},  # duplicate
    ]
    try:
        paper_chunked.check_coverage(dup, _CLOSURE)
        assert False, "expected ChunkError on a duplicated fact"
    except paper_chunked.ChunkError as e:
        assert e.phase == "plan"


def test_normalize_coverage_repairs_dupes_strays_and_gaps():
    # normalize_coverage REPAIRS an imperfect plan instead of aborting: dedupe a fact
    # in two sections (keep first), drop a non-closure id, sweep an unassigned closure
    # fact into a final section — every closure fact covered exactly once.
    closure = ["A", "B", "C"]
    sections = [
        {"title": "S1", "label": "sec:1", "fact_ids": ["A", "B"]},
        {"title": "S2", "label": "sec:2", "fact_ids": ["B", "Z"]},  # B duplicate, Z stray
        # C unassigned
    ]
    repaired, log = paper_chunked.normalize_coverage(sections, closure)
    assigned = [f for s in repaired for f in s["fact_ids"]]
    assert sorted(assigned) == ["A", "B", "C"]   # each closure fact exactly once
    assert assigned.count("B") == 1              # deduped (kept first section)
    assert "Z" not in assigned                    # stray dropped
    assert log                                    # repairs were logged
    paper_chunked.check_coverage(repaired, closure)   # now passes the strict check


def test_paper_write_imperfect_plan_is_repaired_not_aborted():
    # A planner that leaves a closure fact unassigned is now REPAIRED (the fact is
    # swept into a final 'Additional results' section) — the write PROCEEDS and every
    # fact is still presented (self-containedness), instead of aborting.
    partial = [
        {"title": "Introduction", "label": "sec:intro", "fact_ids": []},
        {"title": "Main", "label": "sec:main", "fact_ids": _CLOSURE[:2]},
        # _CLOSURE[2] unassigned -> swept into an appended 'Additional results' section
    ]
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        with _fake_codex_router(
                planner_out=_planner_out(partial),
                section_outs=[_section_body("sec:intro", "Introduction"),
                              _section_body("sec:main", "Main results"),
                              _section_body("sec:additional", "Additional results")]):
            out = server.paper_write()
        assert out["status"] == "ok", out
        assert out["chunked"] is True
        assert out["sections"] == 3           # intro + main + swept 'Additional results'
        assert (pdir / "paper" / "main.tex").exists()



# --------------------------------------------------------------------------- #
# PER-SECTION FILL + STITCH                                                     #
# --------------------------------------------------------------------------- #

def test_stitch_contains_preamble_sections_bib_and_end_document():
    tex = paper_chunked.stitch(
        _PREAMBLE, _FRONTMATTER,
        [_section_body("sec:intro", "Introduction"),
         "\\section{Main results}\\label{sec:main}\nBody.\n"],
        _BIB)
    assert "\\documentclass{amsart}" in tex
    assert "\\begin{document}" in tex
    assert "\\section{Introduction}" in tex
    assert "\\section{Main results}" in tex
    assert "\\begin{thebibliography}" in tex
    assert tex.rstrip().endswith("\\end{document}")


def test_paper_write_chunked_stitches_and_merges_provenance():
    fid_a = _CLOSURE[2]
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        with _fake_codex_router(
                planner_out=_planner_out(_FULL_SECTIONS),
                section_outs=[
                    _section_body("sec:intro", "Introduction"),
                    _section_body("sec:main", "Main results",
                                  prov={"thm:main": fid_a}),
                ]):
            out = server.paper_write()
        assert out["status"] == "ok" and out["chunked"] is True and out["sections"] == 2
        tex_path = Path(out["tex_path"])
        tex = tex_path.read_text(encoding="utf-8")
        # stitched whole: preamble + BOTH sections + bib + end
        assert "\\documentclass{amsart}" in tex
        assert "\\section{Introduction}" in tex and "\\section{Main results}" in tex
        assert "\\begin{thebibliography}" in tex
        assert tex.rstrip().endswith("\\end{document}")
        # the source fact id lives ONLY in the side provenance file, never the tex
        assert fid_a not in tex
        prov_path = Path(out["provenance_path"])
        assert prov_path.name == ".provenance.json"
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        assert prov == {"thm:main": fid_a}


def test_paper_write_chunked_leak_in_any_section_quarantines():
    # A leaked 16-hex fact id in ONE section body trips the leak gate on the
    # STITCHED whole → quarantine to main.leaky.tex, no main.tex.
    leaky_section = ("\\section{Main results}\\label{sec:main}\n"
                     "Derived from fact 001bf4602805c852.\n")  # 16-hex id in the tex
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        with _fake_codex_router(
                planner_out=_planner_out(_FULL_SECTIONS),
                section_outs=[_section_body("sec:intro", "Introduction"),
                              leaky_section]):
            out = server.paper_write()
        assert out["status"] == "leak"
        assert out["chunked"] is True
        assert not (pdir / "paper" / "main.tex").exists()
        assert Path(out["leaky_tex_path"]).exists()


# --------------------------------------------------------------------------- #
# HONESTY                                                                       #
# --------------------------------------------------------------------------- #

def test_paper_write_chunked_planner_nonzero_fails_no_main_tex():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        with _fake_codex_router(planner_out="boom", section_outs=[], planner_rc=1):
            out = server.paper_write()
        assert out["status"] == "chunk_failed"
        assert out["failed_phase"] == "plan"
        assert not (pdir / "paper" / "main.tex").exists()
        assert out["log_path"] and Path(out["log_path"]).exists()


def test_paper_write_chunked_section_nonzero_fails_no_main_tex():
    # The planner is ok, the FIRST section writer returns non-ok → honest abort:
    # status='chunk_failed', failed_phase='section:<label>', NO main.tex.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        with _fake_codex_router(
                planner_out=_planner_out(_FULL_SECTIONS),
                section_outs=["", ""], section_rc=1):
            out = server.paper_write()
        assert out["status"] == "chunk_failed"
        assert out["failed_phase"] == "section:sec:intro"
        assert not (pdir / "paper" / "main.tex").exists()
        assert out["log_path"] and Path(out["log_path"]).exists()


def test_paper_write_chunked_section_empty_stdout_is_honest():
    # An empty stdout (rc 0 but no output) is NOT ok per classify_outcome → abort.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_PAPER_WRITE_CHUNK_CHARS="100"):
        with _fake_codex_router(
                planner_out=_planner_out(_FULL_SECTIONS),
                section_outs=["", ""], section_rc=0):
            out = server.paper_write()
        assert out["status"] == "chunk_failed"
        assert out["failed_phase"].startswith("section:")
        assert not (pdir / "paper" / "main.tex").exists()


# --------------------------------------------------------------------------- #
# standalone runner                                                             #
# --------------------------------------------------------------------------- #

def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"PASS ({len(fns)} chunked tests)")


if __name__ == "__main__":
    _run_all()
