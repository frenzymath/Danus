"""Smoke tests for danus.core — the truth layer.

Exercises local memory, global memory (verifiable/evidence rule + status), and
the fact graph (content addressing + DAG + cascade revoke + external_refs). The
local->global->fact promotion is an *agent* behavior (prose); here we only drive
the data-structure calls the agent would make.

Runs standalone (``python -m danus.core.tests.test_core``) and under pytest.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from danus.core import (
    FactGraph,
    GlobalMemory,
    LocalMemory,
    clean_external_refs,
    compute_fact_id,
    parse_frontmatter,
)
from danus.core import glossary as _glossary
from danus.core import factgraph as _factgraph
from danus.core._util import read_jsonl


def test_local_memory_edge_cases():
    with tempfile.TemporaryDirectory() as d:
        lm = LocalMemory(Path(d) / "worker")
        # a non-dict record is rejected
        try:
            lm.append("notes", "not a dict")  # type: ignore[arg-type]
            assert False, "should reject non-dict record"
        except ValueError:
            pass
        # appending to a brand-new channel registers it on the fly
        assert "scratch" not in lm.channels
        lm.append("scratch", {"x": 1})
        assert "scratch" in lm.channels
        assert lm.read("scratch")[0]["record"] == {"x": 1}


def test_global_memory_edge_cases():
    with tempfile.TemporaryDirectory() as d:
        gm = GlobalMemory(Path(d) / "p")
        # unknown kind is rejected
        try:
            gm.append("bogus_kind", claim="c", evidence="e", author="w")
            assert False, "should reject unknown kind"
        except ValueError:
            pass
        # invalid status is rejected
        try:
            gm.set_status("someid", "not-a-status")
            assert False, "should reject invalid status"
        except ValueError:
            pass
        # search: status fold-in + limit_per_kind + zero-score drop
        for i in range(3):
            gm.append("plan", claim=f"reduce to q>={i} case", evidence="", author="w")
        first = gm.read("plan")[0]["id"]
        gm.set_status(first, "supported")
        res = gm.search("reduce", kinds=["plan"], limit_per_kind=2)
        plan = res["results_by_kind"]["plan"]
        assert plan["count"] == 2  # limit_per_kind honored
        # the folded-in status appears on whichever ranked entry is `first`
        for hit in plan["results"]:
            if hit["entry"]["id"] == first:
                assert hit["entry"]["status"] == "supported"
        # a query matching nothing yields zero results (score<=0 break)
        assert gm.search("zzzquarkxyz", kinds=["plan"])["results_by_kind"]["plan"]["count"] == 0


def test_util_read_jsonl_missing_and_garbage():
    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "nope.jsonl"
        assert read_jsonl(missing) == []  # missing file -> []
        garbage = Path(d) / "g.jsonl"
        garbage.write_text(
            '{"ok": 1}\n'          # valid dict
            "\n"                    # blank line skipped
            "not json at all\n"     # JSONDecodeError skipped
            "[1, 2, 3]\n"           # valid JSON but not a dict -> skipped
            '{"ok": 2}\n',
            encoding="utf-8",
        )
        rows = read_jsonl(garbage)
        assert rows == [{"ok": 1}, {"ok": 2}]  # only the well-formed dicts survive


def test_schema_clean_external_refs_extra_keys():
    # an entry with a key NOT in EXTERNAL_REF_KEYS: canonical keys first, extras
    # appended in sorted order (exercises the extra-key preserve branch)
    out = clean_external_refs([{"note": "z", "title": "T", "key": "K", "aardvark": 1}])
    assert out == [{"key": "K", "title": "T", "aardvark": 1, "note": "z"}]
    assert list(out[0]) == ["key", "title", "aardvark", "note"]


def test_glossary_flatten_and_undefined():
    # falsy -> {}
    assert _glossary.flatten(None) == {} and _glossary.flatten({}) == {}
    # nested {version, terms:{term:{definition, aliases}}} shape + flat shape
    nested = {"version": 1, "terms": {"S_M": {"definition": "a set", "aliases": ["SM"]}}}
    fl = _glossary.flatten(nested)
    assert fl["S_M"] == "a set" and fl["SM"] == "a set"  # alias inherits definition
    assert _glossary.flatten({"K_F": "canonical"}) == {"K_F": "canonical"}  # flat entry
    # undefined_symbols: a token whose base-form (sans arg list) is defined is OK.
    # "S_M(x)" is an interesting token; its base "S_M" is in `defined` -> not flagged.
    assert _glossary.undefined_symbols(
        statement="S_M(x) applied", proof="", defined={"S_M"}) == []
    # and if neither the token nor its base is defined, it IS flagged
    assert _glossary.undefined_symbols(
        statement="S_M(x) applied", proof="", defined=set()) == ["S_M(x)"]


def test_glossary_global_load_and_fallback():
    # the real packaged resource loads and flattens to a non-empty dict
    _glossary.global_glossary.cache_clear()
    real = _glossary.global_glossary()
    assert isinstance(real, dict)
    # missing resource -> _load_global_text returns None -> global_glossary() == {}
    orig = _glossary._load_global_text
    _glossary._load_global_text = lambda: None
    _glossary.global_glossary.cache_clear()
    try:
        assert _glossary.global_glossary() == {}
        assert _glossary.global_terms() == set()
    finally:
        _glossary._load_global_text = orig
        _glossary.global_glossary.cache_clear()
    # broken JSON in the resource -> JSONDecodeError -> {}
    _glossary._load_global_text = lambda: "{not: valid json"
    _glossary.global_glossary.cache_clear()
    try:
        assert _glossary.global_glossary() == {}
    finally:
        _glossary._load_global_text = orig
        _glossary.global_glossary.cache_clear()
    # confirm the real load path via importlib.resources returns text (not None)
    assert _glossary._load_global_text() is not None


def test_glossary_missing_resource_fallback():
    # point the loader at a package with no glossary resource -> None (the
    # FileNotFoundError/OSError branch of _load_global_text)
    import danus.core.glossary as g
    orig_res = g._GLOBAL_RESOURCE
    g._GLOBAL_RESOURCE = "does_not_exist_anywhere.json"
    try:
        assert g._load_global_text() is None
    finally:
        g._GLOBAL_RESOURCE = orig_res


def test_factgraph_edge_cases():
    with tempfile.TemporaryDirectory() as d:
        fg = FactGraph(Path(d) / "proj")
        # intuition is serialized (## intuition block)
        fid = fg.add(problem_id="P", author="w", statement="A holds", proof="pf",
                     intuition="the key idea is X")
        assert "## intuition" in fg.get_raw(fid) and "the key idea is X" in fg.get_raw(fid)

        # search: `limit` cap is honored (three matching facts, limit=2)
        for s in ("B one", "B two", "B three"):
            fg.add(problem_id="P", author="w", statement=s, proof="about B")
        assert len(fg.search("B", limit=2)) == 2

        # glossary() with corrupt JSON on disk -> {} (never raises)
        fg.glossary_path.parent.mkdir(parents=True, exist_ok=True)
        fg.glossary_path.write_text("{not json", encoding="utf-8")
        assert fg.glossary() == {}

        # revoke of an unknown fact_id raises
        try:
            fg.revoke("deadbeefdeadbeef", reason="nope")
            assert False, "should raise on unknown fact_id"
        except ValueError:
            pass


def test_factgraph_set_external_refs_edge_cases():
    with tempfile.TemporaryDirectory() as d:
        fg = FactGraph(Path(d) / "proj")
        # unknown fact_id -> ValueError
        try:
            fg.set_external_refs("deadbeefdeadbeef", [])
            assert False, "should raise on unknown fact_id"
        except ValueError as e:
            assert "unknown fact_id" in str(e)

        # a fact whose file has NO external_refs line (legacy) -> the line is inserted
        fid = compute_fact_id(problem_id="P", predecessors=[], glossary_introduces={},
                              statement="L holds", proof="pf L")
        fg.facts_dir.mkdir(parents=True, exist_ok=True)
        legacy = (f"---\nfact_id: {fid}\nproblem_id: P\nauthor: w\n"
                  "predecessors: []\nglossary_introduces: {}\n---\n\n"
                  "## statement\nL holds\n\n## proof\npf L\n")
        fg._path(fid).write_text(legacy, encoding="utf-8")
        refs = [{"key": "K1", "title": "T1"}]
        assert fg.set_external_refs(fid, refs) == refs
        assert fg.external_refs(fid) == refs
        assert "external_refs:" in fg.get_raw(fid)

        # a malformed file (no frontmatter close) -> ValueError
        bad = compute_fact_id(problem_id="P", predecessors=[], glossary_introduces={},
                              statement="M", proof="p")
        fg._path(bad).write_text("---\nfact_id: x\nno close here\n", encoding="utf-8")
        try:
            fg.set_external_refs(bad, refs)
            assert False, "should raise on malformed frontmatter"
        except ValueError as e:
            assert "malformed" in str(e)


def test_parse_frontmatter_edge_cases():
    # external_refs with invalid JSON payload -> [] (JSONDecodeError branch)
    bad_refs = ("---\nfact_id: x\nproblem_id: P\nauthor: w\npredecessors: []\n"
                "glossary_introduces: {}\nexternal_refs: {not valid json\n---\n\n"
                "## statement\ns\n\n## proof\np\n")
    assert parse_frontmatter(bad_refs)["external_refs"] == []

    # a glossary block terminated by a NON-glossary, non-special line
    # (in_gloss stays True until a line fails _GLOSS_LINE_RE -> in_gloss=False)
    with_gloss = ("---\nfact_id: x\nproblem_id: P\nauthor: w\npredecessors: []\n"
                  "glossary_introduces:\n  X: a manifold\n"
                  "some_other_field: value\n"        # not a glossary line -> terminates block
                  "external_refs: []\n---\n\n"
                  "## statement\ns\n\n## proof\np\n")
    parsed = parse_frontmatter(with_gloss)
    assert parsed["glossary_introduces"] == {"X": "a manifold"}
    assert parsed["external_refs"] == []


def test_statement_of_helper():
    # a fact with a section after statement: statement stops at the next `##`
    raw = "## statement\nA holds\nand more\n\n## proof\nirrelevant\n"
    assert _factgraph.statement_of(raw) == "A holds and more"


def test_local_memory():
    with tempfile.TemporaryDirectory() as d:
        lm = LocalMemory(Path(d) / "worker_high")
        lm.append("notes", {"thought": "try a Beatty-sequence decomposition"})
        lm.append("events", {"did": "searched arxiv for floor-sum bounds"})
        hits = lm.search("Beatty decomposition")
        assert hits["results_by_channel"]["notes"]["count"] == 1
        assert len(lm.read("events")) >= 2  # explicit event + auto breadcrumb


def test_global_memory():
    with tempfile.TemporaryDirectory() as d:
        gm = GlobalMemory(Path(d) / "project")

        # judgment (verifiable=false): no evidence required
        pid = gm.append("plan", claim="reduce to the q>=2 case", evidence="", author="worker_high")
        assert [e for e in gm.read("plan") if e["id"] == pid][0]["status"] == "open"

        # main-agent strategic guidance
        gm.append("master_guidance", claim="prioritize the symplectic-rank route",
                  evidence="pro: the rank obstruction is the crux", author="main_agent")

        # main-agent elaboration (judgment synthesis; verifiable=false, cited fact_ids in links)
        eid = gm.append("elaboration", claim="**Not solved.** Main blocker: rank obstruction",
                        evidence="## 0. Mathematical verdict\n**Not solved.** ...", author="main_agent",
                        links={"fact_ids": ["abc123"]})
        eentry = [e for e in gm.read("elaboration") if e["id"] == eid][0]
        assert eentry["status"] == "open" and eentry["links"]["fact_ids"] == ["abc123"]

        # verification trace (logged by fact_submit; verifiable=false, extra fields allowed)
        vid = gm.append("verification", claim="Lemma L fails for n=2", evidence="verdict: correct",
                        author="worker_xhigh", verdict="correct", fact_id="abc123")
        ventry = [e for e in gm.read("verification") if e["id"] == vid][0]
        assert ventry["verdict"] == "correct" and ventry["fact_id"] == "abc123"

        # verifiable kind with empty evidence is rejected
        try:
            gm.append("conclusion", claim="c", evidence="", author="w")
            assert False, "should require evidence"
        except ValueError:
            pass

        # a verifiable claim, then status transitions (agent-driven)
        gid = gm.append("counterexample", claim="Lemma L fails for n=2",
                        evidence="Take X=P^1; ... QED.", author="worker_xhigh")
        assert [e for e in gm.read("counterexample") if e["id"] == gid][0]["status"] == "unverified"
        gm.set_status(gid, "verified", fact_id="abc123")
        entry = [e for e in gm.read("counterexample") if e["id"] == gid][0]
        assert entry["status"] == "verified" and entry["fact_id"] == "abc123"


def test_factgraph():
    with tempfile.TemporaryDirectory() as d:
        fg = FactGraph(Path(d) / "proj2")
        base = fg.add(problem_id="P", author="P_high", statement="A holds", proof="proof of A",
                      glossary_introduces={"X": "a complex manifold"})
        child = fg.add(problem_id="P", author="P_high", statement="B from A", proof="uses A",
                       predecessors=[base])
        grand = fg.add(problem_id="P", author="P_high", statement="C from B", proof="uses B",
                       predecessors=[child])

        # content addressing: same content (incl. glossary) -> same id
        assert base == compute_fact_id(problem_id="P", predecessors=[],
                                       glossary_introduces={"X": "a complex manifold"},
                                       statement="A holds", proof="proof of A")
        assert fg.predecessors(child) == [base]
        assert set(fg.descendants(base)) == {child, grand}
        assert "## statement" in fg.get_raw(base) and "## proof" in fg.get_raw(base)

        # derived fact index: BM25 search over fact bodies, rebuilt on demand
        hits = fg.search("B from A")
        assert hits and hits[0]["fact_id"] == child
        assert hits[0]["statement"] == "B from A"          # snippet is the ## statement body
        assert all(h["score"] > 0 for h in hits)           # zero-score hits are dropped
        assert fg.search("nonexistent symplectic quark") == []

        # glossary: serialized in the node, merged into the project glossary, parsed back
        assert "X: a complex manifold" in fg.get_raw(base)
        assert fg.glossary().get("X") == "a complex manifold"
        assert parse_frontmatter(fg.get_raw(base))["glossary_introduces"] == {"X": "a complex manifold"}

        # coverage check: a symbol defined in a predecessor is OK; an undefined one is flagged
        assert fg.undefined_symbols(statement="K_F equals zero", proof="by X",
                                    predecessors=[base], glossary_introduces={}) == ["K_F"]
        assert fg.undefined_symbols(statement="X is nice", proof="X is a manifold",
                                    predecessors=[base]) == []
        # global glossary: universal notation counts as defined everywhere (no project def needed)
        assert fg.undefined_symbols(statement="let epsilon in R+", proof="Z+ is nonempty") == []

        # cascade revoke + predecessor-revoked refusal
        revoked = fg.revoke(base, reason="A was wrong")
        assert set(revoked) == {base, child, grand}
        assert not fg.exists(base) and not fg.exists(child) and not fg.exists(grand)
        try:
            fg.add(problem_id="P", author="P_high", statement="D from A", proof="uses A",
                   predecessors=[base])
            assert False, "should refuse revoked predecessor"
        except ValueError as e:
            assert "predecessor_revoked" in str(e)


def test_external_refs():
    with tempfile.TemporaryDirectory() as d:
        fg = FactGraph(Path(d) / "proj3")
        refs = [{"key": "HL26", "authors": ["Han", "Liu"], "title": "On X",
                 "arxiv": "2603.03817", "year": 2026, "cited_for": "Theorem 1.2"}]

        # 1) BACKWARD COMPAT (load-bearing): external_refs is NOT hashed, so adding
        #    refs does not change the fact_id, and the id equals the bare compute_fact_id.
        bare = compute_fact_id(problem_id="P", predecessors=[], glossary_introduces={},
                               statement="A holds", proof="proof of A")
        fid_a = fg.add(problem_id="P", author="w", statement="A holds", proof="proof of A",
                       external_refs=refs)
        assert fid_a == bare, "external_refs must not change the fact_id"

        # 2) refs round-trip through serialize/parse and the read helper
        assert fg.external_refs(fid_a) == refs
        assert parse_frontmatter(fg.get_raw(fid_a))["external_refs"] == refs
        assert "external_refs:" in fg.get_raw(fid_a)

        # 3) same content + no refs => SAME id (dedup); re-adding is idempotent
        fid_a2 = fg.add(problem_id="P", author="w", statement="A holds", proof="proof of A")
        assert fid_a2 == fid_a

        # 4) a fact written without refs reads back as [] (and old-format files too)
        fid_b = fg.add(problem_id="P", author="w", statement="B holds", proof="proof of B")
        assert fg.external_refs(fid_b) == []
        legacy = ("---\nfact_id: deadbeefdeadbeef\nproblem_id: P\nauthor: w\n"
                  "predecessors: []\nglossary_introduces: {}\n---\n\n## statement\nx\n\n## proof\ny\n")
        assert parse_frontmatter(legacy)["external_refs"] == []   # no field -> default []

        # 5) set_external_refs (the auditor's path): rewrites refs, preserves id + body
        body_before = fg.get_raw(fid_b).split("## statement", 1)[1]
        out = fg.set_external_refs(fid_b, refs)
        assert out == refs and fg.external_refs(fid_b) == refs
        assert fg.exists(fid_b)                                            # id/file unchanged
        assert fg.get_raw(fid_b).split("## statement", 1)[1] == body_before  # body untouched

        # 6) normalization: non-dict entries dropped, canonical key order, [] for empty
        assert clean_external_refs([{"title": "T", "key": "K"}, "junk", 7]) == [{"key": "K", "title": "T"}]
        assert clean_external_refs(None) == [] and clean_external_refs([]) == []


def main() -> None:
    test_local_memory()
    print("  [ok] local memory append/search")
    test_local_memory_edge_cases()
    print("  [ok] local memory: non-dict record rejected + new-channel registration")
    test_global_memory()
    print("  [ok] global memory append/status/search + evidence rule")
    test_global_memory_edge_cases()
    print("  [ok] global memory: unknown kind / bad status / search limit+fold-in")
    test_util_read_jsonl_missing_and_garbage()
    print("  [ok] _util.read_jsonl: missing file + garbage/non-dict lines skipped")
    test_schema_clean_external_refs_extra_keys()
    print("  [ok] schema.clean_external_refs: extra keys preserved (sorted)")
    test_glossary_flatten_and_undefined()
    print("  [ok] glossary flatten (nested+flat) + undefined base-form")
    test_glossary_global_load_and_fallback()
    print("  [ok] glossary global load + missing/broken resource fallbacks")
    test_glossary_missing_resource_fallback()
    print("  [ok] glossary _load_global_text missing-resource -> None")
    test_factgraph()
    print("  [ok] fact graph content-addressing + DAG + cascade revoke")
    test_factgraph_edge_cases()
    print("  [ok] fact graph: intuition/search-limit/corrupt-glossary/revoke-unknown")
    test_factgraph_set_external_refs_edge_cases()
    print("  [ok] fact graph set_external_refs: unknown/legacy-insert/malformed")
    test_parse_frontmatter_edge_cases()
    print("  [ok] parse_frontmatter: bad external_refs JSON + glossary terminator")
    test_statement_of_helper()
    print("  [ok] statement_of stops at next heading")
    test_external_refs()
    print("  [ok] external_refs: not hashed (backward compat) + round-trip + auditor rewrite")
    print("ALL CORE TESTS PASSED")


if __name__ == "__main__":
    main()
