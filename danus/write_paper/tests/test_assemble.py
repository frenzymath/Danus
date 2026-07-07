"""Offline tests for danus.write_paper.assemble — embed-completeness + isolation.

Zero network / API / codex. Asserts the per-role isolation contract
(the writer embeds facts+style+structure; the auditor gets ONLY
main.tex+ledger — no facts, no style; the reviser gets no fact graph), that every
role embeds AGENTS.md verbatim, and that a missing required file raises.

Runs standalone (``python -m danus.write_paper.tests.test_assemble``) and under pytest.
"""

from __future__ import annotations

from pathlib import Path

from danus.write_paper import assemble

from ._fixtures import SKILL_DIR, env, temp_project, write_ledger, write_main_tex


def _fixed(rel: str) -> str:
    return (SKILL_DIR / rel).read_text(encoding="utf-8")


def _fact_proof_text() -> str:
    # a verbatim slice of a fact's ## proof body — must appear ONLY in the writer
    return "The perfect squares grow by the consecutive odd numbers"


def test_writer_embeds_everything_verbatim():
    with temp_project() as pdir:
        p = assemble.build_prompt("writer", pdir)
    # AGENTS.md (the PRIME DIRECTIVE) verbatim
    assert "## 0. PRIME DIRECTIVE" in p
    assert _fixed("roles/AGENTS.md") in p
    # role prompt + style + structure + boilerplate, each verbatim
    assert _fixed("roles/PAPER_WRITER_PROMPT.md") in p
    assert _fixed("style/STYLE_GUIDE.md") in p
    assert _fixed("style/PAPER_STRUCTURE.md") in p
    assert _fixed("boilerplate/acknowledgement.md") in p
    # project brief + ledger
    assert "PROJECT_BRIEF — odd-sum" in p
    assert "REFERENCE_LEDGER" in p and "AC24" in p
    # each selected fact's statement + proof text (verbatim), all three facts
    assert "the sum of the first $n$ positive odd numbers equals $n^2$" in p  # main statement
    assert "We argue by induction on $n$" in p                                # main proof
    assert _fact_proof_text() in p                                            # square_recurrence proof
    assert "one-step telescoping relation" in p                              # odd_recurrence proof
    # section delimiters present so codex/tests can navigate
    assert "===== BEGIN FACT_GRAPH_CONTENT =====" in p
    assert "===== BEGIN AGENTS.md =====" in p
    # STRIP CONTRACT: the fact frontmatter must NOT reach the writer — no fact_id,
    # no author line — even though the proof text above is embedded verbatim. The
    # predecessor DAG header is kept (the paper needs it for internal \ref).
    assert "fact_id:" not in p, "fact frontmatter fact_id must be stripped"
    assert "author:" not in p, "fact frontmatter author must be stripped"
    assert "predecessors (DAG):" in p, "predecessor DAG header is kept for cross-refs"


def test_writer_headline_selects_facts_plus_predecessors():
    # headline = the main fact only → still pulls in both predecessors (DAG), in
    # topological order (predecessors before the main result). We key on each
    # fact's ## proof body text (frontmatter/fact_id is stripped), so order is read
    # from where the mathematics lands.
    with temp_project() as pdir:
        p = assemble.build_prompt("writer", pdir, headline=["fact_odd_sum_main"])
    # predecessor slugs still appear via the DAG header line, not as frontmatter
    assert "predecessors (DAG): fact_odd_recurrence, fact_square_recurrence" in p
    i_pred = p.index("one-step telescoping relation")          # odd_recurrence proof
    i_main = p.index("We argue by induction on $n$")           # main proof
    assert i_pred < i_main, "predecessor must be embedded before the fact that needs it"

    # headline = a single leaf with no predecessors → the other leaf is excluded
    with temp_project() as pdir:
        p2 = assemble.build_prompt("writer", pdir, headline=["fact_square_recurrence"])
    assert _fact_proof_text() in p2                             # square_recurrence proof present
    assert "We argue by induction on $n$" not in p2            # main excluded
    assert "one-step telescoping relation" not in p2           # odd_recurrence excluded


def test_auditor_isolation_no_facts_no_style():
    with temp_project(with_tex=True) as pdir:
        p = assemble.build_prompt("auditor", pdir)
    # embeds what it needs: AGENTS.md, the auditor prompt, main.tex, the ledger
    assert _fixed("roles/AGENTS.md") in p
    assert _fixed("roles/REFERENCE_AUDITOR_PROMPT.md") in p
    assert "\\documentclass{amsart}" in p          # main.tex embedded
    assert "REFERENCE_LEDGER" in p
    # ISOLATION: no fact-graph proof text, no writer/reviser role prompt, no style
    assert _fact_proof_text() not in p
    assert "We argue by induction on $n$" not in p
    assert _fixed("style/STYLE_GUIDE.md") not in p
    assert _fixed("style/PAPER_STRUCTURE.md") not in p
    # the STYLE_GUIDE / PAPER_STRUCTURE files are not embedded as sections
    assert "===== BEGIN STYLE_GUIDE.md =====" not in p
    assert "===== BEGIN PAPER_STRUCTURE.md =====" not in p
    assert _fixed("roles/PAPER_WRITER_PROMPT.md") not in p


def test_verifier_isolation_main_tex_ledger_findings_no_facts_no_style():
    with temp_project(with_tex=True) as pdir:
        p = assemble.build_prompt(
            "verifier", pdir,
            findings="WORKLIST: verify AC24 (authors); verify Exm20 (venue).",
        )
    # embeds what it needs: AGENTS.md, the verifier prompt, main.tex, the ledger,
    # and the auditor's findings
    assert _fixed("roles/AGENTS.md") in p
    assert _fixed("roles/REFERENCE_VERIFIER_PROMPT.md") in p
    assert "\\documentclass{amsart}" in p          # main.tex (bibliography + \cite) embedded
    assert "REFERENCE_LEDGER" in p and "AC24" in p
    assert "===== BEGIN AUDITOR_FINDINGS =====" in p
    assert "verify AC24 (authors)" in p             # the auditor's worklist embedded
    # ISOLATION: no fact-graph proof text, no style/structure, no writer role prompt
    assert _fact_proof_text() not in p
    assert "We argue by induction on $n$" not in p
    assert _fixed("style/STYLE_GUIDE.md") not in p
    assert _fixed("style/PAPER_STRUCTURE.md") not in p
    assert "===== BEGIN STYLE_GUIDE.md =====" not in p
    assert "===== BEGIN PAPER_STRUCTURE.md =====" not in p
    assert _fixed("roles/PAPER_WRITER_PROMPT.md") not in p


def test_verifier_no_findings_default_note():
    # no findings passed -> a clear default note (re-check every unverified row)
    with temp_project(with_tex=True) as pdir:
        p = assemble.build_prompt("verifier", pdir)
    assert "no auditor findings passed" in p


def test_reviser_isolation_no_fact_graph():
    with temp_project(with_tex=True) as pdir:
        p = assemble.build_prompt(
            "reviser", pdir,
            compile_log="! Undefined control sequence \\foo",
            notes="rewrite the intro opener",
        )
    # embeds what it needs: AGENTS.md, reviser prompt, style, main.tex, the trigger
    assert _fixed("roles/AGENTS.md") in p
    assert _fixed("roles/PAPER_REVISER_PROMPT.md") in p
    assert _fixed("style/STYLE_GUIDE.md") in p
    assert "\\documentclass{amsart}" in p
    assert "Undefined control sequence" in p      # compile_log trigger
    assert "rewrite the intro opener" in p        # notes trigger
    # ISOLATION: no fact-graph statement/proof/intuition text
    assert _fact_proof_text() not in p
    assert "We argue by induction on $n$" not in p
    assert "the sum of the first $n$ positive odd numbers equals $n^2$" not in p


def test_reviser_citation_fixes_under_trigger_no_fact_graph_with_mode():
    # seam: citation_fixes is embedded as its own labelled trigger block, distinct
    # from operator notes; isolation still holds (no fact graph) and the MODE label
    # is present.
    fixes = "AC24: correct year to 2024, arXiv:2401.00001; Exm20: keep, normalize authors"
    with temp_project(with_tex=True) as pdir:
        p = assemble.build_prompt("reviser", pdir, citation_fixes=fixes, notes="tighten intro")
    # citation_fixes lands under the TRIGGER, in its own labelled block
    assert fixes in p
    assert "citation_fixes (the verifier's per-entry replacement suggestions" in p
    # its own block, distinct from operator notes
    assert "notes (operator editorial direction" in p
    assert "tighten intro" in p
    # notes/citation_fixes present, no compile_log -> targeted-notes mode
    assert "MODE: targeted-notes" in p
    # ISOLATION preserved: no fact graph
    assert _fact_proof_text() not in p
    assert "We argue by induction on $n$" not in p


def test_reviser_trigger_modes():
    # the MODE line keys off the trigger type
    assert "MODE: compile-fix\n" in assemble._reviser_trigger("! err", None, None) + "\n"
    assert "MODE: targeted-notes" in assemble._reviser_trigger(None, "some notes", None)
    assert "MODE: targeted-notes" in assemble._reviser_trigger(None, None, "some fixes")
    assert "MODE: style-audit-pass" in assemble._reviser_trigger(None, None, None)
    # P2: compile_log + notes/fixes -> the COMBINED mode; the citation_fixes/notes
    # are STILL carried (not deferred/dropped when a compile error also needs fixing).
    combined = assemble._reviser_trigger("! err", "some notes", "some fixes")
    assert "MODE: compile-fix+targeted" in combined
    assert "citation_fixes" in combined and "some fixes" in combined
    assert "some notes" in combined and "compile_log" in combined
    # pure compile-fix stays pure (no combined suffix) when nothing else is pending
    assert "MODE: compile-fix\n" in assemble._reviser_trigger("! err", None, None) + "\n"


def test_brief_headline_accepts_hex_fact_ids():
    # P3: content-addressed 16-hex ids in the brief must be parsed, not only fact_
    # slugs — otherwise a hex-id deployment's brief path silently reads as unset.
    with temp_project() as pdir:
        brief = pdir / "paper" / "PROJECT_BRIEF.md"
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text("# brief\nheadline_fact_ids: f469b7af3103b419\n", encoding="utf-8")
        assert assemble.brief_headline_fact_ids(pdir) == ["f469b7af3103b419"]
        # a fact_ slug + a hex id + prose on the line -> both ids kept, prose dropped
        brief.write_text("headline_fact_ids: fact_main, 001bf4602805c852 (main thm)\n",
                         encoding="utf-8")
        got = assemble.brief_headline_fact_ids(pdir)
        assert "fact_main" in got and "001bf4602805c852" in got
        # an angle-bracket placeholder still yields [] (no real id present)
        brief.write_text("headline_fact_ids: <fact ids here>\n", encoding="utf-8")
        assert assemble.brief_headline_fact_ids(pdir) == []


def test_headline_unknown_fact_id_raises():
    # a headline naming a fact id not in the graph must raise loudly (assemble.py:96)
    with temp_project() as pdir:
        try:
            assemble.fact_graph_content(pdir, headline=["fact_does_not_exist"])
            assert False, "unknown headline fact id should raise ValueError"
        except ValueError as e:
            assert "unknown fact id" in str(e)


def test_fact_graph_content_empty_project():
    # a project whose fact graph has no facts. With the brief's headline_fact_ids
    # blanked and no TARGET.md, the default resolves to UNSET and refuses (raises
    # TargetUnsetError) rather than silently embedding all facts. An explicit empty
    # headline still yields the no-facts sentinel (used for genuinely empty graphs).
    with temp_project() as pdir:
        facts = Path(pdir) / "fact_graph" / "facts"
        for f in facts.glob("*.md"):
            f.unlink()
        brief = Path(pdir) / "paper" / "PROJECT_BRIEF.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "headline_fact_ids: fact_odd_sum_main", "headline_fact_ids:"
            ),
            encoding="utf-8",
        )
        # unset target -> refuse (no guess, no all-facts fallback)
        try:
            assemble.fact_graph_content(pdir)
            assert False, "unset target on an empty graph must raise TargetUnsetError"
        except assemble.TargetUnsetError:
            pass
        # explicit empty headline -> the sentinel (no crash)
        assert "no verified facts" in assemble.fact_graph_content(pdir, headline=[])


def test_toposort_cycle_appends_deterministically(monkeypatch=None):
    # a (should-not-happen) predecessor cycle must not hang or drop facts: the
    # remaining nodes are appended deterministically (assemble.py:122). We stub a
    # tiny FactGraph-like object exposing list()/predecessors().
    class _CyclicFG:
        def list(self):
            return ["a", "b"]

        def predecessors(self, fid):
            return {"a": ["b"], "b": ["a"]}[fid]  # mutual cycle

    ordered = assemble._toposort_with_predecessors(_CyclicFG(), None)
    assert sorted(ordered) == ["a", "b"], "a cycle must still yield every fact, once"
    assert len(ordered) == 2


def test_anchor_block_embeds_text_and_names_binary():
    # drop a tiny fake anchor dir under the skill dir: one text exemplar (embedded
    # verbatim) + one undecodable "binary" file (named, not embedded). Point
    # DANUS_WRITE_PAPER_SKILL_DIR at a temp skill dir so we can add the anchor
    # without touching the shipped skill.
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as sd:
        skill = Path(sd)
        # mirror the real skill dir so read_fixed still finds roles/style/boilerplate
        shutil.copytree(SKILL_DIR, skill, dirs_exist_ok=True)
        adir = skill / "style" / "anchors" / "my_anchor"
        adir.mkdir(parents=True)
        (adir / "exemplar.tex").write_text("\\section{An exemplar opener}\n", encoding="utf-8")
        # an undecodable byte sequence stands in for a binary (e.g. a .pdf)
        (adir / "figure.pdf").write_bytes(b"\xff\xfe\x00\x01binary\x80")
        with env(DANUS_WRITE_PAPER_SKILL_DIR=str(skill)):
            body = assemble._anchor_block("my_anchor")
            assert body is not None
            assert "An exemplar opener" in body                 # text embedded verbatim
            assert "exemplar.tex" in body
            assert "figure.pdf (binary; not embedded)" in body  # binary named, not embedded

            # it reaches the writer prompt as a STRUCTURAL_EXEMPLAR section ONLY when
            # the brief names it (deterministic, brief-driven — no free anchor arg).
            with temp_project() as pdir:
                brief = Path(pdir) / "paper" / "PROJECT_BRIEF.md"
                brief.write_text(
                    brief.read_text(encoding="utf-8").replace(
                        "structural_exemplar:", "structural_exemplar: my_anchor"
                    ),
                    encoding="utf-8",
                )
                p = assemble.build_prompt("writer", pdir)
            assert "===== BEGIN STRUCTURAL_EXEMPLAR (my_anchor) =====" in p
            assert "An exemplar opener" in p


def test_anchor_block_none_and_missing_dir():
    # no anchor requested -> None; a requested anchor whose dir is absent -> None
    assert assemble._anchor_block(None) is None
    assert assemble._anchor_block("") is None
    with temp_project() as pdir:  # shipped skill has no 'ghost' anchor
        assert assemble._anchor_block("ghost_anchor_that_does_not_exist") is None


def test_anchor_block_empty_dir_returns_none():
    # an anchor dir that exists but holds no files -> None (parts empty; assemble.py:188)
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as sd:
        skill = Path(sd)
        shutil.copytree(SKILL_DIR, skill, dirs_exist_ok=True)
        (skill / "style" / "anchors" / "empty_anchor").mkdir(parents=True)
        with env(DANUS_WRITE_PAPER_SKILL_DIR=str(skill)):
            assert assemble._anchor_block("empty_anchor") is None


def test_revision_log_tail_reads_and_truncates():
    # existing REVISION_LOG.md is read (assemble.py:274-275); an over-long log is
    # truncated with a marker.
    with temp_project() as pdir:
        log = Path(pdir) / "paper" / "REVISION_LOG.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("round one notes\n", encoding="utf-8")
        assert assemble._revision_log_tail(pdir) == "round one notes\n"
        # over the cap -> truncated
        log.write_text("x" * 9000, encoding="utf-8")
        tail = assemble._revision_log_tail(pdir, max_chars=100)
        assert tail.endswith("… (truncated)\n") and len(tail) < 9000


def test_reviser_trigger_no_trigger_default_note():
    # no compile_log and no notes -> the default style-audit note (assemble.py:285)
    t = assemble._reviser_trigger(None, None)
    assert "no explicit trigger passed" in t
    # and it lands in the reviser prompt's TRIGGER section
    with temp_project(with_tex=True) as pdir:
        p = assemble.build_prompt("reviser", pdir)
    assert "no explicit trigger passed" in p


def test_missing_required_file_raises():
    # missing project main.tex for the auditor
    with temp_project(with_tex=False) as pdir:
        try:
            assemble.build_prompt("auditor", pdir)
            assert False, "auditor with no main.tex should raise"
        except FileNotFoundError:
            pass
    # missing fixed skill file → raise (point DANUS_WRITE_PAPER_SKILL_DIR at an empty dir)
    with temp_project() as pdir, env(DANUS_WRITE_PAPER_SKILL_DIR=str(pdir)):
        try:
            assemble.build_prompt("writer", pdir)
            assert False, "writer with no fixed files should raise"
        except FileNotFoundError:
            pass
    # unknown role
    with temp_project() as pdir:
        try:
            assemble.build_prompt("nope", pdir)
            assert False, "unknown role should raise"
        except ValueError:
            pass


def main() -> None:
    test_writer_embeds_everything_verbatim()
    print("  [ok] writer embeds AGENTS.md + role + style + structure + brief + ledger + facts (verbatim)")
    test_writer_headline_selects_facts_plus_predecessors()
    print("  [ok] writer headline pulls transitive predecessors, topologically ordered")
    test_auditor_isolation_no_facts_no_style()
    print("  [ok] auditor isolation: main.tex+ledger only; NO facts, NO style/structure")
    test_verifier_isolation_main_tex_ledger_findings_no_facts_no_style()
    print("  [ok] verifier isolation: main.tex+ledger+findings; NO facts, NO style/structure")
    test_verifier_no_findings_default_note()
    print("  [ok] verifier with no findings -> default re-check note")
    test_reviser_isolation_no_fact_graph()
    print("  [ok] reviser isolation: main.tex+log+trigger; NO fact graph")
    test_reviser_citation_fixes_under_trigger_no_fact_graph_with_mode()
    print("  [ok] reviser citation_fixes: own trigger block, MODE label, still no fact graph")
    test_reviser_trigger_modes()
    print("  [ok] reviser trigger MODE line keys off trigger type")
    test_headline_unknown_fact_id_raises()
    print("  [ok] unknown headline fact id -> ValueError")
    test_fact_graph_content_empty_project()
    print("  [ok] empty fact graph -> 'no verified facts' sentinel")
    test_toposort_cycle_appends_deterministically()
    print("  [ok] predecessor cycle -> every fact appended once (no hang/drop)")
    test_anchor_block_embeds_text_and_names_binary()
    print("  [ok] style anchor: text embedded verbatim, binary named; reaches writer prompt")
    test_anchor_block_none_and_missing_dir()
    print("  [ok] anchor None / empty / missing dir -> None")
    test_anchor_block_empty_dir_returns_none()
    print("  [ok] anchor dir present but empty -> None")
    test_revision_log_tail_reads_and_truncates()
    print("  [ok] revision-log tail read + truncation")
    test_reviser_trigger_no_trigger_default_note()
    print("  [ok] reviser with no trigger -> default style-audit note")
    test_missing_required_file_raises()
    print("  [ok] missing required fixed/project file raises; unknown role raises")
    print("ALL ASSEMBLE TESTS PASSED")


if __name__ == "__main__":
    main()
