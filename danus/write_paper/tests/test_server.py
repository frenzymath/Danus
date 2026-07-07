"""Offline tests for danus.write_paper.server — the four MCP tools.

Monkeypatches ``server.driver.run_codex`` with a fake CompletedProcess (no codex,
no network, no API). Verifies: paper_write writes main.tex + parses [GAP:] +
returns a small dict; a nonzero codex exit yields status != ok and writes nothing
(no false success); reference_audit returns findings and writes no main.tex;
reference_verify verifies the flagged refs online and writes the ledger delta;
paper_revise overwrites main.tex + appends REVISION_LOG.md.

Runs standalone (``python -m danus.write_paper.tests.test_server``) and under pytest.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path

from danus.write_paper import server

from ._fixtures import EXAMPLE_PROJECT, env, temp_project, write_ledger, write_main_tex


@contextmanager
def _fake_codex(stdout="", returncode=0, stderr="", raise_exc=None):
    """Replace server.driver.run_codex with a stub returning a CompletedProcess."""
    orig = server.driver.run_codex

    def fake(prompt, *, model, effort, timeout=0, networked=False, gateway_role="verifier"):
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(args=["fake"], returncode=returncode,
                                           stdout=stdout, stderr=stderr)

    server.driver.run_codex = fake
    try:
        yield
    finally:
        server.driver.run_codex = orig


@contextmanager
def _fake_codex_seq(outputs):
    """Replace server.driver.run_codex with a stub that returns a SEQUENCE of stdout
    values across successive calls (for the reviser's compile-retry re-drives). Each
    element is either a stdout str (returncode 0) or an (stdout, returncode, stderr)
    tuple. The last element is repeated if more calls arrive. Captures the prompts
    it was driven with in ``.prompts``."""
    orig = server.driver.run_codex
    calls = {"n": 0, "prompts": []}

    def fake(prompt, *, model, effort, timeout=0, networked=False, gateway_role="verifier"):
        calls["prompts"].append(prompt)
        i = min(calls["n"], len(outputs) - 1)
        calls["n"] += 1
        item = outputs[i]
        if isinstance(item, tuple):
            out, rc, err = (list(item) + ["", 0, ""])[:3]
        else:
            out, rc, err = item, 0, ""
        return subprocess.CompletedProcess(args=["fake"], returncode=rc, stdout=out, stderr=err)

    server.driver.run_codex = fake
    try:
        yield calls
    finally:
        server.driver.run_codex = orig


@contextmanager
def _fake_compile(results):
    """Replace server._compile_check with a stub returning a SEQUENCE of results
    (for the compile-retry loop). Each element is a dict merged over the default
    ``{"ok": True, "log": "", "engine_available": True}``. The last element repeats.
    Captures how many times it was called in ``.n``."""
    orig = server._compile_check
    state = {"n": 0}

    def fake(tex):
        i = min(state["n"], len(results) - 1)
        state["n"] += 1
        base = {"ok": True, "log": "", "engine_available": True}
        base.update(results[i])
        return base

    server._compile_check = fake
    try:
        yield state
    finally:
        server._compile_check = orig


def _reviser_edit(find="\\end{document}", replace="REVISED\n\\end{document}", summary="did the edit"):
    """A reviser PATCH with a single anchor-based find/replace edit — applies to ANY
    base containing ``find`` (default the universal ``\\end{document}``), so it works
    across multi-round / evolving-base flow tests. summary=None → degraded (no summary)."""
    s = f"{server._PATCH_SEP}\n<<<<<<< FIND\n{find}\n=======\n{replace}\n>>>>>>> REPLACE"
    if summary is not None:
        s += f"\n{server._REVISION_SUMMARY_SEP}\n{summary}"
    return s


def _reviser_out(tex, summary=None, base=None):
    """Build a reviser PATCH stdout that REPLACES ``base`` (default the seeded minimal
    main.tex) with ``tex`` — a single full-replace find/replace edit — so the applied
    main.tex equals ``tex`` (matching the tests' model) while exercising the real
    patch-apply path. summary=None omits the %%%REVISION_SUMMARY%%% section."""
    from ._fixtures import _MINIMAL_TEX
    b = _MINIMAL_TEX if base is None else base
    s = (f"{server._PATCH_SEP}\n<<<<<<< FIND\n{b}\n=======\n{tex}\n>>>>>>> REPLACE")
    if summary is not None:
        s += f"\n{server._REVISION_SUMMARY_SEP}\n{summary}"
    return s


_GOOD_TEX = (
    "\\documentclass{amsart}\n\\begin{document}\n\\title{T}\n\\maketitle\n"
    "We prove $S(n)=n^2$.\n[GAP: the base case is not shown]\n"
    "some more [GAP: cite for Exm20 unverified]\n\\end{document}\n"
)


def test_paper_write_leak_gate_removes_stale_clean_tex():
    # server.py:138 — if a clean main.tex already exists and a fresh run leaks, the
    # stale clean file is removed (never leave a clean .tex next to a leaky run).
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex_path = pdir / "paper" / "main.tex"
        assert tex_path.exists(), "temp_project(with_tex=True) seeds a clean main.tex"
        leaky_tex = _GOOD_TEX + "\n% derived from fact 161f436b1c2d3e4f\n"
        with _fake_codex(stdout=leaky_tex, returncode=0):
            out = server.paper_write()
        assert out["status"] == "leak"
        assert not tex_path.exists(), "the stale clean main.tex must be removed on a leak"
        assert Path(out["leaky_tex_path"]).exists()


def test_paper_revise_gap_fill_carries_feedback_notes_and_facts():
    # The main-agent -> reviser INTERFACE: after the whole-doc verifier flags gaps,
    # the main agent passes verifier_feedback + its own notes + the facts it chose to
    # add; the tool embeds those facts' verified proofs so the reviser can prove them
    # into the paper. Assert all three reach the reviser as one 'gap-fill' trigger.
    revised = _reviser_out(
        "\\documentclass{amsart}\n\\begin{document}\nR\n\\end{document}\n",
        summary="added the recurrence lemma with proof")
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        with _fake_codex_seq([revised]) as calls, _fake_compile([{"ok": True}]):
            out = server.paper_revise(
                verifier_feedback="The paper uses the recurrence S(n+1)=S(n)+(2n+1) but never proves it.",
                add_facts=["fact_odd_recurrence"],
                notes="present it as a Lemma before the main theorem")
        assert out["status"] == "ok"
        assert out["gap_fill_facts"] == ["fact_odd_recurrence"]
        p = calls["prompts"][0]
        assert "MODE: gap-fill" in p
        assert "VERIFIER FEEDBACK" in p and "never proves it" in p       # verifier opinion
        assert "FACTS TO ADD" in p and "S(n+1)" in p                     # the added fact's content
        assert "present it as a Lemma" in p                              # main-agent opinion


def test_paper_revise_appends_to_existing_log():
    # server.py — a second revise round appends to the existing REVISION_LOG
    revised = _reviser_edit(summary="round summary body")
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        log = pdir / "paper" / "REVISION_LOG.md"
        with _fake_codex(stdout=revised, returncode=0), _fake_compile([{"ok": True}]):
            server.paper_revise(notes="round 1")
            server.paper_revise(compile_log="! err round 2")
        text = log.read_text(encoding="utf-8")
        # both rounds recorded; the header appears exactly once (append, not rewrite)
        assert text.count("reviser (danus.write_paper)") == 2
        assert text.count("# REVISION_LOG") == 1
        assert "trigger:** notes" in text and "trigger:** compile_log" in text
        assert "mode:** compile-fix" in text and "mode:** targeted-notes" in text


def test_build_app_registers_all_tools():
    # server.py — build_app wires the paper tools onto a FastMCP app
    app = server.build_app()
    assert app is not None
    assert set(server._TOOLS) == {"paper_subgraph", "paper_write", "reference_audit",
                                  "reference_verify", "paper_revise", "paper_verify_math"}


def test_main_module_runs_build_app(monkeypatch=None):
    # __main__.py — `python -m danus.write_paper` builds the app and calls .run().
    # We stub FastMCP.run so nothing blocks / opens stdio, then run the module.
    import runpy
    from mcp.server.fastmcp import FastMCP

    orig_run = FastMCP.run
    calls = {"n": 0}
    FastMCP.run = lambda self, *a, **k: calls.__setitem__("n", calls["n"] + 1)
    try:
        runpy.run_module("danus.write_paper", run_name="__main__")
    finally:
        FastMCP.run = orig_run
    assert calls["n"] == 1, "__main__ must build the app and call run() exactly once"


def test_paper_write_reports_resolved_headline_from_brief():
    # server.paper_write flows the default through resolve_headline and reports the
    # target ids used + their source (honesty). The example brief names
    # headline_fact_ids: fact_odd_sum_main -> source 'brief'.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok"
        assert out["headline"] == ["fact_odd_sum_main"]
        assert out["headline_source"] == "brief"


def test_paper_write_needs_target_when_brief_blank_and_no_target_md():
    # brief blank AND no TARGET.md -> the target is unset; paper_write REFUSES to
    # guess: status 'needs_target', candidate terminal facts, NO main.tex written.
    from pathlib import Path as _P
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        brief = _P(pdir) / "paper" / "PROJECT_BRIEF.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "headline_fact_ids: fact_odd_sum_main", "headline_fact_ids:"),
            encoding="utf-8")
        with _fake_codex(stdout=_GOOD_TEX, returncode=0):
            out = server.paper_write()
        assert out["status"] == "needs_target"
        assert out["headline_source"] == "unset" and out["headline"] == []
        assert "candidates" in out and out["candidates"] == ["fact_odd_sum_main"]
        assert "message" in out and "danus finalize" in out["message"]
        assert not _P(out["tex_path"]).exists(), "no main.tex when the target is unset"


def test_paper_write_reads_target_md_when_brief_blank():
    # brief blank but a finalized <project>/TARGET.md present -> source 'target',
    # main.tex written.
    from pathlib import Path as _P
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        brief = _P(pdir) / "paper" / "PROJECT_BRIEF.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "headline_fact_ids: fact_odd_sum_main", "headline_fact_ids:"),
            encoding="utf-8")
        from danus.write_paper import assemble as _assemble
        _assemble.write_target_fact_ids(pdir, ["fact_odd_sum_main"])
        with _fake_codex(stdout=_GOOD_TEX, returncode=0):
            out = server.paper_write()
        assert out["status"] == "ok"
        assert out["headline"] == ["fact_odd_sum_main"]
        assert out["headline_source"] == "target"


def test_paper_write_explicit_headline_arg_overrides_brief():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        out = server.paper_write(headline=["fact_square_recurrence"])
        assert out["headline"] == ["fact_square_recurrence"]
        assert out["headline_source"] == "arg"


def test_paper_write_success_writes_tex_and_parses_gaps():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok" and out["returncode"] == 0
        tex_path = Path(out["tex_path"])
        assert tex_path.exists() and tex_path.read_text(encoding="utf-8") == _GOOD_TEX
        assert out["gaps"] == ["[GAP: the base case is not shown]",
                               "[GAP: cite for Exm20 unverified]"]
        # small return: no full .tex leaked into the dict
        assert "stdout" not in out and _GOOD_TEX not in str(out)


def test_paper_write_writes_provenance_and_keeps_ids_out_of_tex():
    # The writer appends a %%%PROVENANCE%%% block (label -> source fact id). The
    # tool splits it off BEFORE the leak gate, so the 16-hex fact id (which would
    # otherwise trip the leak gate) lands only in the side .provenance.json, and
    # main.tex stays clean.
    import json as _json
    fid = "001bf4602805c852"  # a 16-hex fact id — a leak pattern IF it were in the tex
    stdout = _GOOD_TEX + f'%%%PROVENANCE%%%\n{{"thm:main": "{fid}", "lem:key": "0037fa1ad469c818"}}\n'
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=stdout, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok", "the fact id is in provenance, not the tex -> no leak"
        tex_path = Path(out["tex_path"])
        assert tex_path.read_text(encoding="utf-8") == _GOOD_TEX  # tex is the clean pre-marker part
        assert fid not in tex_path.read_text(encoding="utf-8")    # id never in the .tex
        prov_path = Path(out["provenance_path"])
        assert prov_path.name == ".provenance.json" and prov_path.exists()
        prov = _json.loads(prov_path.read_text(encoding="utf-8"))
        assert prov == {"thm:main": fid, "lem:key": "0037fa1ad469c818"}


def test_strip_code_fence_unwraps_only_an_outer_fence():
    # a wrapping ```tex ... ``` is stripped; clean LaTeX is left untouched
    fenced = "```tex\n" + _GOOD_TEX + "```\n"
    stripped = server._strip_code_fence(fenced)
    assert stripped.startswith("\\documentclass") and "```" not in stripped
    assert server._strip_code_fence(_GOOD_TEX) == _GOOD_TEX  # no fence -> unchanged


def test_paper_write_strips_markdown_fence_so_tex_compiles():
    # Real-world failure MatTan surfaced: the writer wrapped its whole output in a
    # ```tex fence, so main.tex began with ``` and failed to compile. The tool must
    # strip the outer fence — even the provenance block inside the fence is recovered.
    import json as _json
    fid = "001bf4602805c852"
    inner = _GOOD_TEX + f'%%%PROVENANCE%%%\n{{"thm:main": "{fid}"}}\n'
    stdout = "```tex\n" + inner + "```\n"      # writer wrapped EVERYTHING in a fence
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=stdout, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok"
        tex = Path(out["tex_path"]).read_text(encoding="utf-8")
        assert tex.startswith("\\documentclass") and "```" not in tex, "outer fence must be stripped"
        # provenance inside the fence is still recovered to the side file
        prov = _json.loads(Path(out["provenance_path"]).read_text(encoding="utf-8"))
        assert prov == {"thm:main": fid}


def test_paper_write_no_provenance_marker_is_backward_compatible():
    # A plain-tex writer output (no %%%PROVENANCE%%% marker) is unchanged: whole
    # stdout is the tex, no .provenance.json written.
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok"
        assert out["provenance_path"] is None
        assert not (pdir / "paper" / ".provenance.json").exists()


def test_paper_write_malformed_provenance_is_skipped_tex_still_written():
    # A malformed provenance block after the marker is skipped (no .provenance.json),
    # but the clean tex before the marker is still written.
    stdout = _GOOD_TEX + "%%%PROVENANCE%%%\nnot valid json{{{\n"
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=stdout, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok"
        assert out["provenance_path"] is None
        assert Path(out["tex_path"]).read_text(encoding="utf-8") == _GOOD_TEX
        assert not (pdir / "paper" / ".provenance.json").exists()


@contextmanager
def _fake_do_stop(fn):
    """Patch danus.orchestration.cli.do_stop (imported at call time inside
    server._ensure_swarm_stopped) with ``fn``."""
    import danus.orchestration.cli as cli
    orig = cli.do_stop
    cli.do_stop = fn
    try:
        yield
    finally:
        cli.do_stop = orig


def test_paper_write_keeps_swarm_by_default():
    # Item A: entering write-paper does NOT stop the swarm on its own — a partial
    # result may be written up while the swarm keeps exploring. Default = no stop.
    def boom(target, force=False):
        raise AssertionError("do_stop must NOT be called by default (Item A)")

    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0), _fake_do_stop(boom):
        out = server.paper_write()  # default stop_workers=False
        assert out["status"] == "ok"
        assert out["swarm_stop"] == {"skipped": "stop_workers=False"}


def test_paper_write_stop_workers_true_stops():
    # The main agent can still request a stop (after asking the operator).
    calls = {"force": None, "target": None}

    def fake(target, force=False):
        calls["target"], calls["force"] = target, force
        return [{"worker": "high", "result": "stopped"}]

    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0), _fake_do_stop(fake):
        out = server.paper_write(stop_workers=True)
        assert out["status"] == "ok"
        assert out["swarm_stop"]["result"] == [{"worker": "high", "result": "stopped"}]
        assert calls["force"] is False, "must be a GRACEFUL stop (no --force)"


def test_paper_write_swarm_stop_idempotent_on_idle():
    # stop_workers=True on an already-idle project: do_stop reports not-running; no error.
    def fake(target, force=False):
        return [{"worker": "high", "result": "not-running"}]

    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0), _fake_do_stop(fake):
        out = server.paper_write(stop_workers=True)
        assert out["status"] == "ok"
        assert "error" not in out["swarm_stop"]
        assert out["swarm_stop"]["result"][0]["result"] == "not-running"


def test_paper_write_env_keeps_swarm_even_when_requested():
    # DANUS_KEEP_SWARM_ON_WRITE=1 forces keep-running even if the caller asks to stop.
    def boom(target, force=False):
        raise AssertionError("do_stop must NOT be called when env forces keep")

    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_KEEP_SWARM_ON_WRITE="1"), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0), _fake_do_stop(boom):
        out = server.paper_write(stop_workers=True)
        assert out["status"] == "ok"
        assert out["swarm_stop"] == {"skipped": "DANUS_KEEP_SWARM_ON_WRITE"}


def test_paper_write_swarm_stop_failure_is_isolated():
    # A do_stop that raises (when a stop IS requested) must NOT block paper
    # generation: the tex is written normally and only swarm_stop.error records it.
    def boom(target, force=False):
        raise RuntimeError("stop exploded")

    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0), _fake_do_stop(boom):
        out = server.paper_write(stop_workers=True)
        assert out["status"] == "ok", "a stop failure must not fail the paper"
        assert Path(out["tex_path"]).exists()
        assert out["swarm_stop"] == {"error": "RuntimeError: stop exploded"}


def test_swarm_stop_no_import_cycle():
    # _ensure_swarm_stopped's deferred import of orchestration.cli must not cycle.
    from danus.orchestration.cli import do_stop  # noqa: F401
    assert callable(server._ensure_swarm_stopped)


def test_paper_write_no_swarm_stop_on_needs_target():
    # When the target is UNSET, paper_write refuses and must NOT stop the swarm
    # (we have not committed to the paper).
    def boom(target, force=False):
        raise AssertionError("do_stop must NOT be called on a needs_target refusal")

    with temp_project(with_ledger=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_do_stop(boom):
        # blank the brief's headline + ensure no TARGET.md so the target is unset
        brief = pdir / "paper" / "PROJECT_BRIEF.md"
        if brief.exists():
            brief.write_text("# brief\n(no headline)\n", encoding="utf-8")
        (pdir / "TARGET.md").unlink(missing_ok=True)
        out = server.paper_write()
        assert out["status"] == "needs_target"
        assert "swarm_stop" not in out


def test_paper_write_nonzero_exit_is_honest_and_writes_nothing():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="partial junk", returncode=3, stderr="codex blew up"):
        out = server.paper_write()
        assert out["status"] != "ok" and out["status"] == "error"
        assert out["returncode"] == 3
        assert "codex blew up" in out["stderr_tail"]
        assert not Path(out["tex_path"]).exists(), "no main.tex on a failed run (no false success)"


def test_paper_write_empty_stdout_is_honest():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="   \n", returncode=0):
        out = server.paper_write()
        assert out["status"] == "error" and "empty" in out["error"]
        assert not Path(out["tex_path"]).exists()


def test_paper_write_timeout_is_honest():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(raise_exc=subprocess.TimeoutExpired(cmd="codex", timeout=1)):
        out = server.paper_write()
        assert out["status"] == "timeout"
        assert not Path(out["tex_path"]).exists()


def test_reference_audit_returns_findings_and_writes_no_tex():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        before = (pdir / "paper" / "main.tex").read_text(encoding="utf-8")
        with _fake_codex(stdout="FINDINGS: AC24 unverified; Exm20 unverified.", returncode=0):
            out = server.reference_audit()
        after = (pdir / "paper" / "main.tex").read_text(encoding="utf-8")
    assert out["status"] == "ok"
    assert "unverified" in out["findings"]
    assert out["ledger_path"].endswith("REFERENCE_LEDGER.md")
    assert before == after, "the auditor must not touch main.tex"


def test_reference_audit_nonzero_is_honest():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="", returncode=1, stderr="oops"):
        out = server.reference_audit()
        assert out["status"] == "error" and out["findings"] == ""


def test_paper_revise_overwrites_and_appends_log():
    revised_tex = "\\documentclass{amsart}\n\\begin{document}\nREVISED\n\\end{document}\n"
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        original = tex.read_text(encoding="utf-8")
        assert not log.exists()
        with _fake_codex(stdout=_reviser_out(revised_tex, summary="tightened the intro"),
                         returncode=0), _fake_compile([{"ok": True}]):
            out = server.paper_revise(notes="tighten the intro")
        assert out["status"] == "ok"
        assert out["compile"] == "ok" and out["compile_attempts"] == 1
        # the WRITTEN tex is the split MAIN_TEX section, not the raw stdout
        assert tex.read_text(encoding="utf-8") == revised_tex != original
        assert log.exists() and "reviser (danus.write_paper)" in log.read_text(encoding="utf-8")


def test_paper_revise_nonzero_does_not_overwrite():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        original = tex.read_text(encoding="utf-8")
        with _fake_codex(stdout="broken", returncode=2, stderr="bad"):
            out = server.paper_revise(compile_log="! error")
        assert out["status"] == "error"
        assert tex.read_text(encoding="utf-8") == original, "no overwrite on failure"
        assert not log.exists(), "no log entry on a failed round"


def test_project_resolution_by_name():
    # DANUS_AGENTS_ROOT + project name; the example project as <root>/proj
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as root:
        proj = Path(root) / "odd_sum"
        shutil.copytree(EXAMPLE_PROJECT, proj)
        write_main_tex(proj)
        write_ledger(proj)
        with env(DANUS_AGENTS_ROOT=root, DANUS_PROJECT_DIR=None):
            with _fake_codex(stdout="FINDINGS: ok", returncode=0):
                out = server.reference_audit(project="odd_sum")
            assert out["status"] == "ok"
            assert out["ledger_path"].startswith(str(proj))
            # bad names rejected
            for bad in ("../evil", "a/b", "/abs"):
                try:
                    server.reference_audit(project=bad)
                    assert False, f"should reject {bad!r}"
                except RuntimeError:
                    pass


def test_paper_write_leak_gate_withholds_tex_with_fake_fact_id():
    # invariant #8: a .tex that leaks a 16-hex fact_id is caught → status 'leak',
    # main.tex NOT written, output quarantined to main.leaky.tex
    leaky_tex = _GOOD_TEX + "\n% derived from fact 161f436b1c2d3e4f\n"
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=leaky_tex, returncode=0):
        out = server.paper_write()
        assert out["status"] == "leak", "a leaked fact_id must not yield status ok"
        assert out["leak_findings"] and any("16-hex" in f for f in out["leak_findings"])
        assert not Path(out["tex_path"]).exists(), "a leaky .tex must NOT be kept as main.tex"
        assert Path(out["leaky_tex_path"]).exists(), "the leaky output is quarantined for inspection"


def test_paper_write_leak_gate_allows_paper_vocabulary():
    # the paper set does NOT forbid worker/verifier/predecessors — they appear in
    # real papers and the paper keeps a predecessor-DAG note
    ok_tex = (
        "\\documentclass{amsart}\n\\begin{document}\n"
        "The verifier of the protocol and each worker predecessors chain is fine.\n"
        "\\end{document}\n"
    )
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=ok_tex, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok" and out["leak_findings"] == []
        assert Path(out["tex_path"]).read_text(encoding="utf-8") == ok_tex


def test_per_service_model_effort_are_independent():
    # DANUS_WRITE_PAPER_* wins for write_paper; DANUS_HUMAN_SUMMARY_* wins for
    # human_summary; both fall back to the neutral DANUS_CODEX_* — the two services
    # are independently tunable.
    from danus.human_summary import server as hs_server

    with env(DANUS_WRITE_PAPER_MODEL="wp-model", DANUS_WRITE_PAPER_EFFORT="wp-eff",
             DANUS_HUMAN_SUMMARY_MODEL="hs-model", DANUS_HUMAN_SUMMARY_EFFORT="hs-eff",
             DANUS_CODEX_MODEL="neutral-model", DANUS_CODEX_EFFORT="neutral-eff"):
        assert server._model() == "wp-model" and server._effort() == "wp-eff"
        assert hs_server._model() == "hs-model" and hs_server._effort() == "hs-eff"

    # per-service unset → both fall back to the neutral DANUS_CODEX_*
    with env(DANUS_WRITE_PAPER_MODEL=None, DANUS_WRITE_PAPER_EFFORT=None,
             DANUS_HUMAN_SUMMARY_MODEL=None, DANUS_HUMAN_SUMMARY_EFFORT=None,
             DANUS_CODEX_MODEL="neutral-model", DANUS_CODEX_EFFORT="neutral-eff"):
        assert server._model() == "neutral-model" and server._effort() == "neutral-eff"
        assert hs_server._model() == "neutral-model" and hs_server._effort() == "neutral-eff"


_VERDICT_JSON = (
    '[{"key": "AC24", "verdict": "verified", '
    '"confirmed_metadata": {"authors": "A. Author, B. Coauthor", '
    '"title": "A note on telescoping sums", "year": 2024, "venue": "J. Example Math.", '
    '"arxiv_id": "2401.00001"}, "source_url": "https://arxiv.org/abs/2401.00001", '
    '"note": "arxiv abs page confirms same authors+title"},'
    ' {"key": "Exm20", "verdict": "corrected", '
    '"confirmed_metadata": {"authors": "C. Example", "title": "Elementary induction, revisited", '
    '"year": 2020}, "source_url": "https://doi.org/10.0000/example", '
    '"note": "publisher page corrects the venue"}]'
)


def test_reference_verify_writes_ledger_on_ok_never_main_tex():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        ledger = pdir / "paper" / "REFERENCE_LEDGER.md"
        tex_before = tex.read_text(encoding="utf-8")
        with _fake_codex(stdout=_VERDICT_JSON, returncode=0):
            out = server.reference_verify(findings="verify AC24; verify Exm20")
        assert out["status"] == "ok"
        # well-formed verdicts parsed
        assert len(out["verdicts"]) == 2
        keys = {v["key"] for v in out["verdicts"]}
        assert keys == {"AC24", "Exm20"}
        assert all(v["verdict"] in server._VALID_VERDICTS for v in out["verdicts"])
        # ledger updated IN PLACE (single table, no append-only delta section)
        led = ledger.read_text(encoding="utf-8")
        assert "verifier delta" not in led, "no append-only delta section (single-table)"
        assert "verified-by: verifier" in led
        assert "https://arxiv.org/abs/2401.00001" in led
        # the key appears exactly once (in place, not body-row + delta-row)
        assert led.count("## AC24") == 1
        # main.tex NEVER touched by the verifier
        assert tex.read_text(encoding="utf-8") == tex_before


# The shape a REAL codex run emits (captured from a live reference_verify smoke): one
# ```yaml``` fenced block per entry, column-0 fields + an indented
# confirmed_metadata sub-mapping (or `null`). This is the regression the offline
# JSON fixture missed — the model prefers YAML, and the parser must handle it.
_VERDICT_YAML = (
    "```yaml\n"
    "key: Vaswani17\n"
    "verdict: verified\n"
    "confirmed_metadata:\n"
    "  authors: Ashish Vaswani; Noam Shazeer; Niki Parmar\n"
    "  title: Attention Is All You Need\n"
    "  venue: arXiv preprint\n"
    "  year: 2017\n"
    '  arxiv_id: "1706.03762"\n'
    "source_url: https://arxiv.org/abs/1706.03762\n"
    "note: arXiv record matches the cited title, id, year, and authors.\n"
    "replacement_suggestion: keep the cite; normalize the bibitem authors.\n"
    "```\n\n"
    "```yaml\n"
    "key: GAN\n"
    "verdict: corrected\n"
    "confirmed_metadata:\n"
    "  authors: Ian J. Goodfellow; et al.\n"
    "  title: Generative Adversarial Networks\n"
    "  venue: arXiv preprint\n"
    "  year: 2014\n"
    '  arxiv_id: "1406.2661"\n'
    "source_url: https://arxiv.org/abs/1406.2661\n"
    "note: arXiv confirms 2014, not the claimed 2016 / Journal of Machine Learning.\n"
    "replacement_suggestion: replace the bibitem year/venue with 2014, arXiv:1406.2661.\n"
    "```\n\n"
    "```yaml\n"
    "key: Fabricated\n"
    "verdict: rejected\n"
    "confirmed_metadata: null\n"
    "source_url: null\n"
    "note: arxiv.org/abs/2401.99999 returns 404; no matching paper found.\n"
    "replacement_suggestion: remove or retarget the citation.\n"
    "```\n"
)


def test_parse_verdicts_handles_yaml_blocks():
    """Regression: a real codex emits YAML-ish blocks, not JSON. The parser must
    extract them, honoring the §4 'labelled key/value list' contract."""
    verdicts = server._parse_verdicts(_VERDICT_YAML)
    by_key = {v["key"]: v for v in verdicts}
    assert set(by_key) == {"Vaswani17", "GAN", "Fabricated"}
    assert by_key["Vaswani17"]["verdict"] == "verified"
    # indented confirmed_metadata parsed into a dict; quoted scalar unquoted
    meta = by_key["Vaswani17"]["confirmed_metadata"]
    assert isinstance(meta, dict) and meta["arxiv_id"] == "1706.03762"
    assert by_key["Vaswani17"]["source_url"] == "https://arxiv.org/abs/1706.03762"
    assert by_key["GAN"]["verdict"] == "corrected"
    assert by_key["GAN"]["confirmed_metadata"]["year"] == "2014"
    # `null` maps to None, not the string "null"
    assert by_key["Fabricated"]["verdict"] == "rejected"
    assert by_key["Fabricated"]["confirmed_metadata"] is None
    assert by_key["Fabricated"]["source_url"] is None


def test_reference_verify_promotes_only_sourced_verdicts_from_yaml():
    """End-to-end (fake codex, real YAML shape): ok run parses the YAML, promotes
    verified+corrected (which carry source_url) with verified-by: verifier, records
    rejected without promotion, and never touches main.tex."""
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        ledger = pdir / "paper" / "REFERENCE_LEDGER.md"
        tex_before = tex.read_text(encoding="utf-8")
        with _fake_codex(stdout=_VERDICT_YAML, returncode=0):
            out = server.reference_verify(findings="verify Vaswani17; GAN; Fabricated")
        assert out["status"] == "ok"
        assert {v["key"] for v in out["verdicts"]} == {"Vaswani17", "GAN", "Fabricated"}
        led = ledger.read_text(encoding="utf-8")
        # verified + corrected promoted with source_url
        assert "verified-by: verifier" in led
        assert "https://arxiv.org/abs/1706.03762" in led
        assert "https://arxiv.org/abs/1406.2661" in led
        # rejected recorded IN PLACE but NOT promoted
        assert "verifier delta" not in led, "single-table, no append-only delta"
        assert "## Fabricated" in led
        assert "verified-by: unverified (rejected)" in led
        # each key appears once (in-place update, not duplicated)
        assert led.count("## Vaswani17") == 1 and led.count("## Fabricated") == 1
        # main.tex NEVER touched
        assert tex.read_text(encoding="utf-8") == tex_before


def test_reference_verify_nonzero_writes_nothing():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        ledger = pdir / "paper" / "REFERENCE_LEDGER.md"
        led_before = ledger.read_text(encoding="utf-8")
        with _fake_codex(stdout=_VERDICT_JSON, returncode=2, stderr="codex blew up"):
            out = server.reference_verify(findings="verify AC24")
        assert out["status"] == "error" and out["verdicts"] == []
        assert ledger.read_text(encoding="utf-8") == led_before, "no ledger write on nonzero exit"


def test_reference_verify_empty_stdout_writes_nothing():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        ledger = pdir / "paper" / "REFERENCE_LEDGER.md"
        led_before = ledger.read_text(encoding="utf-8")
        with _fake_codex(stdout="   \n", returncode=0):
            out = server.reference_verify()
        assert out["status"] == "error" and out["verdicts"] == []
        assert ledger.read_text(encoding="utf-8") == led_before


def test_reference_verify_timeout_writes_nothing():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        ledger = pdir / "paper" / "REFERENCE_LEDGER.md"
        led_before = ledger.read_text(encoding="utf-8")
        with _fake_codex(raise_exc=subprocess.TimeoutExpired(cmd="codex", timeout=1)):
            out = server.reference_verify()
        assert out["status"] == "timeout" and out["verdicts"] == []
        assert ledger.read_text(encoding="utf-8") == led_before


def test_apply_ledger_verdicts_updates_row_in_place():
    # The core fix: a seeded `verified-by: unverified` row is rewritten IN PLACE to
    # `verified-by: verifier` — no stale dual state, no duplicate section, no delta.
    import tempfile
    seeded = (
        "# REFERENCE_LEDGER\n\n"
        "Seeded from the project's facts.\n\n"
        "## AC24\n"
        "- authors: A. Author\n"
        "- title: A note on telescoping sums\n"
        "- cited_by_facts: fact_x\n"
        "- verified-by: unverified\n\n"
        "## Other\n"
        "- title: untouched\n"
        "- verified-by: unverified\n"
    )
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "REFERENCE_LEDGER.md"
        led.write_text(seeded, encoding="utf-8")
        server._apply_ledger_verdicts(led, [{
            "key": "AC24", "verdict": "corrected",
            "confirmed_metadata": {"authors": "A. Author, B. Coauthor", "year": "2024",
                                   "arxiv_id": "2401.00001"},
            "source_url": "https://arxiv.org/abs/2401.00001",
            "note": "arxiv abs confirms",
        }])
        out = led.read_text(encoding="utf-8")
        # AC24 promoted in place: exactly one section, no lingering 'unverified' for it
        assert out.count("## AC24") == 1
        ac24 = out.split("## AC24", 1)[1].split("## Other", 1)[0]
        assert "verified-by: verifier" in ac24
        assert "verified-by: unverified" not in ac24, "no stale dual state for the key"
        assert "source_url: https://arxiv.org/abs/2401.00001" in ac24
        assert "authors: A. Author, B. Coauthor" in ac24  # corrected metadata applied
        # untouched key keeps its seeded state
        assert "## Other" in out and "untouched" in out
        assert "verifier delta" not in out


def test_apply_ledger_verdicts_compacts_legacy_delta():
    # Migration: a ledger already polluted with an append-only '## verifier delta'
    # section is compacted to the single-table form on the next write.
    import tempfile
    polluted = (
        "# REFERENCE_LEDGER\n\n"
        "## AC24\n- verified-by: unverified\n\n"
        "## verifier delta — 2026-07-04T00:00:00Z\n\n"
        "### AC24 — verified\n- source_url: https://x\n- verified-by: verifier\n"
    )
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "REFERENCE_LEDGER.md"
        led.write_text(polluted, encoding="utf-8")
        server._apply_ledger_verdicts(led, [{
            "key": "AC24", "verdict": "verified",
            "confirmed_metadata": {}, "source_url": "https://x", "note": "",
        }])
        out = led.read_text(encoding="utf-8")
        assert "verifier delta" not in out, "legacy delta section compacted away"
        assert out.count("## AC24") == 1


def test_reference_verify_web_unreachable_all_unverifiable_no_false_promotion():
    # a degraded/offline run: codex returns only `unverifiable` verdicts. The ledger
    # rows are updated in place but NOTHING is promoted to verified-by: verifier.
    degraded = (
        '[{"key": "AC24", "verdict": "unverifiable", "confirmed_metadata": {}, '
        '"source_url": "", "note": "web unreachable; no arxiv hit"},'
        ' {"key": "Exm20", "verdict": "unverifiable", "confirmed_metadata": {}, '
        '"source_url": "", "note": "no authoritative source reachable"}]'
    )
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        ledger = pdir / "paper" / "REFERENCE_LEDGER.md"
        with _fake_codex(stdout=degraded, returncode=0):
            out = server.reference_verify(findings="verify AC24; verify Exm20")
        assert out["status"] == "ok"
        assert all(v["verdict"] == "unverifiable" for v in out["verdicts"])
        led = ledger.read_text(encoding="utf-8")
        assert "verified-by: verifier" not in led, "an unverifiable run must not falsely promote"
        assert "verified-by: unverified (unverifiable)" in led


def test_reference_verify_uses_networked_path():
    # reference_verify must drive codex over the NETWORKED path (networked=True); the
    # other tools must not. We capture the kwargs the driver is called with.
    captured = {}

    def fake(prompt, *, model, effort, timeout=0, networked=False, gateway_role="verifier"):
        captured["networked"] = networked
        captured["gateway_role"] = gateway_role
        return subprocess.CompletedProcess(args=["fake"], returncode=0, stdout=_VERDICT_JSON, stderr="")

    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        orig = server.driver.run_codex
        server.driver.run_codex = fake
        try:
            server.reference_verify(findings="verify AC24")
        finally:
            server.driver.run_codex = orig
    assert captured == {"networked": True, "gateway_role": "verifier"}


def test_paper_revise_leak_gate_withholds_leaky_revision():
    # item 6: the reviser now leak-gates its main.tex write-back — a fact_id in the
    # revised .tex must not slip through. status 'leak', main.tex NOT overwritten,
    # no REVISION_LOG entry, output quarantined.
    leaky = _reviser_edit(
        replace="REVISED\n% derived from fact 161f436b1c2d3e4f\n\\end{document}")
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        original = tex.read_text(encoding="utf-8")
        with _fake_codex(stdout=leaky, returncode=0):
            out = server.paper_revise(notes="tighten intro")
        assert out["status"] == "leak"
        assert out["leak_findings"] and any("16-hex" in f for f in out["leak_findings"])
        assert tex.read_text(encoding="utf-8") == original, "leaky revision must not overwrite main.tex"
        assert not log.exists(), "no REVISION_LOG entry on a leaky round"
        assert Path(out["leaky_tex_path"]).exists()


_GOOD_REVISED = "\\documentclass{amsart}\n\\begin{document}\nREVISED\n\\end{document}\n"


def test_paper_revise_log_carries_reviser_summary_not_stub():
    # P3: the REVISION_LOG entry body IS the reviser's %%%REVISION_SUMMARY%%% text.
    summary = "Annotation ledger: 2 macros addressed. Rewrote the intro opener per §8."
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        log = pdir / "paper" / "REVISION_LOG.md"
        with _fake_codex(stdout=_reviser_out(_GOOD_REVISED, summary=summary),
                         returncode=0), _fake_compile([{"ok": True}]):
            out = server.paper_revise(notes="tighten intro")
        assert out["status"] == "ok"
        text = log.read_text(encoding="utf-8")
        assert summary in text, "the log body must be the reviser's real summary"
        # the boilerplate stub phrasing must not appear
        assert "main.tex overwritten with the reviser's output" not in text


def test_paper_revise_degraded_when_no_summary_section():
    # P3 honest degradation: missing %%%REVISION_SUMMARY%%% -> patch still applied +
    # tex written, log records the degradation, does not fabricate a summary.
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        # a patch with NO %%%REVISION_SUMMARY%%% section -> applied, summary None
        with _fake_codex(stdout=_reviser_edit(summary=None), returncode=0), \
                _fake_compile([{"ok": True}]):
            out = server.paper_revise(notes="tighten intro")
        assert out["status"] == "ok"
        assert "REVISED" in tex.read_text(encoding="utf-8"), "the edit was applied"
        assert "degraded: reviser emitted no REVISION_SUMMARY" in log.read_text(encoding="utf-8")


def test_paper_revise_compile_loop_retries_then_succeeds():
    # P2: compile fails once then succeeds -> main.tex written, compile_attempts > 1.
    # A SEQUENCE of codex outputs is returned across the re-drives.
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        # attempt 1 adds a broken macro; attempt 2 (compile-fix) removes it.
        first = _reviser_edit(replace="BROKEN \\foo\n\\end{document}", summary="attempt 1")
        second = _reviser_edit(find="BROKEN \\foo\n", replace="", summary="attempt 2 fixed it")
        with _fake_codex_seq([first, second]) as calls, \
                _fake_compile([{"ok": False, "log": "! Undefined control sequence \\foo"},
                               {"ok": True}]):
            out = server.paper_revise(notes="polish")
        assert out["status"] == "ok" and out["compile"] == "ok"
        assert out["compile_attempts"] == 2
        assert calls["n"] == 2, "the reviser was re-driven once with the failing log"
        assert "BROKEN" not in tex.read_text(encoding="utf-8"), "the compile-fix removed the broken macro"
        # the re-drive carried the failing compile log into the (lightweight) prompt
        assert "Undefined control sequence" in calls["prompts"][1]


def test_paper_revise_compile_retry_is_lightweight_and_preserves_fixes():
    # The compile retry is now a LIGHTWEIGHT, low-effort, targeted compile-FIX of the
    # last attempt's tex — it does NOT re-run the full reviser mode. The citation fix
    # is applied in attempt 1 (baked into that tex), so the minimal compile-fix retry
    # preserves it (it only touches the compile error) — the fix still reaches the paper.
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        # attempt-1 patch adds the citation fix inline; attempt-2 (compile-fix) keeps it.
        a1 = _reviser_edit(replace="REVISED (Molcho & Ranganathan)\n\\end{document}",
                           summary="applied the citation fix")
        a2 = _reviser_edit(find="REVISED (Molcho & Ranganathan)",
                           replace="REVISED (Molcho \\& Ranganathan)", summary="fixed the compile error")
        with _fake_codex_seq([a1, a2]) as calls, \
                _fake_compile([{"ok": False, "log": "! Undefined control sequence\nl.5 \\foo"},
                               {"ok": True}]):
            out = server.paper_revise(
                citation_fixes="replace ABMR21 authors with Molcho & Ranganathan")
        assert out["status"] == "ok" and out["compile"] == "ok" and out["compile_attempts"] == 2
        first, retry = calls["prompts"][0], calls["prompts"][1]
        # attempt 1: the substantive targeted-notes revision, carrying the citation fix.
        assert "MODE: targeted-notes" in first and "Molcho & Ranganathan" in first
        # attempt 2 (retry): the lightweight compile-FIX prompt — NOT a reviser MODE, and
        # it does NOT re-send the citation_fixes trigger (they are already in the tex).
        assert "fixing LaTeX COMPILE ERRORS" in retry
        assert "MODE: " not in retry
        assert "Undefined control sequence" in retry
        # the fix survives into the written paper (the tex carried it through the retry).
        assert "Ranganathan" in (pdir / "paper" / "main.tex").read_text()


def test_paper_revise_compile_loop_exhausts_and_quarantines():
    # P2: compile always fails -> status compile_failed, main.tex NOT overwritten,
    # main.uncompiled.tex present.
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                                  DANUS_WRITE_PAPER_COMPILE_ATTEMPTS="2"):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        original = tex.read_text(encoding="utf-8")
        broken = _reviser_edit(replace="\\foo\n\\end{document}", summary="tried")
        with _fake_codex(stdout=broken, returncode=0), \
                _fake_compile([{"ok": False, "log": "! LaTeX Error: something"}]):
            out = server.paper_revise(compile_log="! initial error")
        assert out["status"] == "compile_failed"
        assert out["compile_attempts"] == 2
        assert tex.read_text(encoding="utf-8") == original, "main.tex must not be overwritten on exhaustion"
        assert Path(out["uncompiled_tex_path"]).exists(), "last attempt quarantined"
        assert "compile_log_tail" in out
        assert not log.exists(), "no REVISION_LOG entry on an exhausted compile"


def test_paper_revise_engine_missing_skips_compile_and_writes_once():
    # P2: engine_available False -> no loop, write once, compile 'skipped: no engine'.
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        with _fake_codex_seq([_reviser_out(_GOOD_REVISED, summary="done")]) as calls, \
                _fake_compile([{"ok": False, "engine_available": False, "log": "pdflatex not installed"}]):
            out = server.paper_revise(notes="polish")
        assert out["status"] == "ok"
        assert out["compile"] == "skipped: no engine" and out["compile_attempts"] == 0
        assert calls["n"] == 1, "engine missing must NOT trigger a re-drive"
        assert tex.read_text(encoding="utf-8") == _GOOD_REVISED
        led = log.read_text(encoding="utf-8")
        assert "skipped: no engine" in led


def test_paper_revise_nonzero_writes_nothing_regression():
    # regression: a non-ok codex exit writes nothing (no tex, no log), even with the
    # compile loop in place. _compile_check must never be reached.
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        tex = pdir / "paper" / "main.tex"
        log = pdir / "paper" / "REVISION_LOG.md"
        original = tex.read_text(encoding="utf-8")
        with _fake_codex(stdout="junk", returncode=2, stderr="boom"):
            out = server.paper_revise(compile_log="! error")
        assert out["status"] == "error"
        assert out["compile"] == "not run" and out["compile_attempts"] == 0
        assert tex.read_text(encoding="utf-8") == original
        assert not log.exists()


def test_paper_revise_citation_fixes_threaded_to_prompt():
    # seam: citation_fixes reaches the reviser prompt (its own labelled block) and
    # sets MODE targeted-notes.
    fixes = "AC24: correct the year to 2024, arXiv:2401.00001"
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        with _fake_codex_seq([_reviser_out(_GOOD_REVISED, summary="applied fixes")]) as calls, \
                _fake_compile([{"ok": True}]):
            out = server.paper_revise(citation_fixes=fixes)
        assert out["status"] == "ok"
        prompt = calls["prompts"][0]
        assert fixes in prompt, "citation_fixes must reach the reviser prompt"
        assert "citation_fixes (the verifier's per-entry replacement suggestions" in prompt
        assert "MODE: targeted-notes" in prompt


# --------------------------------------------------------------------------- #
# per-call diagnostic run log (log_path)                                       #
# --------------------------------------------------------------------------- #

def _read_run_log(out) -> str:
    """Assert out['log_path'] is a real file and return its text."""
    lp = out.get("log_path")
    assert lp, f"expected a log_path, got {lp!r}"
    p = Path(lp)
    assert p.exists(), f"run log file missing at {lp}"
    assert p.name == "log.md" and p.parent.parent.name == ".runs"
    return p.read_text(encoding="utf-8")


def test_run_log_paper_write_success_captures_prompt_stdout_decisions():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0, stderr="some stderr"):
        out = server.paper_write()
        assert out["status"] == "ok"
        text = _read_run_log(out)
    # full stdout + stderr + decisions (write's swarm_stop / gaps) + prompt section
    assert "## INPUT — assembled prompt" in text
    assert _GOOD_TEX in text, "the FULL codex stdout must be in the log"
    assert "some stderr" in text
    assert "## TOOL DECISIONS" in text
    assert "swarm_stop:" in text and "gaps:" in text and "headline:" in text
    assert "## RETURNED ENVELOPE" in text and '"status": "ok"' in text


def test_run_log_captures_full_stderr_not_just_tail():
    # Feed a stderr LONGER than the 2000-char classifier tail; the FULL stderr must
    # be in the log (proves stderr_full, not the truncated stderr_tail).
    long_stderr = "HEADMARK" + ("x" * 5000) + "TAILMARK"
    assert len(long_stderr) > 2000
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0, stderr=long_stderr):
        out = server.paper_write()
        text = _read_run_log(out)
    assert "HEADMARK" in text and "TAILMARK" in text, "the FULL stderr must be logged"
    # the envelope still carries only the tail (unchanged behavior)
    assert "HEADMARK" not in out["stderr_tail"], "the envelope tail is still truncated"


def test_run_log_written_on_failure_nonzero():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="", returncode=3, stderr="codex crashed hard"):
        out = server.paper_write()
        assert out["status"] == "error"
        text = _read_run_log(out)
    assert "codex crashed hard" in text
    assert "status: error" in text and "returncode: 3" in text


def test_run_log_written_on_timeout_raises():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(raise_exc=subprocess.TimeoutExpired(cmd="codex", timeout=1)):
        out = server.paper_write()
        assert out["status"] == "timeout"
        text = _read_run_log(out)
    assert "status: timeout" in text


def test_run_log_paper_write_needs_target_early_return():
    from pathlib import Path as _P
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        brief = _P(pdir) / "paper" / "PROJECT_BRIEF.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "headline_fact_ids: fact_odd_sum_main", "headline_fact_ids:"),
            encoding="utf-8")
        out = server.paper_write()
        assert out["status"] == "needs_target"
        text = _read_run_log(out)
    # early return: no codex was driven -> the log says so, no prompt
    assert "(no prompt — early return before codex was driven)" in text
    assert "(no codex run)" in text
    assert "needs_target: True" in text


def test_run_log_reference_audit():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout="FINDINGS: AC24 unverified.", returncode=0):
        out = server.reference_audit()
        text = _read_run_log(out)
    assert "FINDINGS: AC24 unverified." in text
    assert "findings_len:" in text


def test_run_log_reference_verify_applied_verdicts():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_VERDICT_JSON, returncode=0):
        out = server.reference_verify(findings="verify AC24; Exm20")
        assert out["status"] == "ok"
        text = _read_run_log(out)
    # decisions spot-check: applied verdict keys (verified/corrected w/ source_url)
    assert "verdicts_count: 2" in text
    assert "applied_keys:" in text and "AC24" in text and "Exm20" in text
    assert "networked: True" in text, "reference_verify is the networked tool"


def test_run_log_paper_revise_records_compile_attempts():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None):
        first = _reviser_edit(replace="BROKEN \\foo\n\\end{document}", summary="attempt 1")
        second = _reviser_edit(find="BROKEN \\foo\n", replace="", summary="attempt 2 fixed it")
        with _fake_codex_seq([first, second]), \
                _fake_compile([{"ok": False, "log": "! Undefined control sequence \\foo"},
                               {"ok": True}]):
            out = server.paper_revise(notes="polish")
        assert out["status"] == "ok" and out["compile_attempts"] == 2
        text = _read_run_log(out)
    # ONE log per CALL, holding the LAST attempt's prompt/stdout + per-attempt outcomes
    assert text.count("## Header") == 1, "one run log per paper_revise call"
    assert "compile_attempts: 2" in text
    assert "compile_outcomes: ['failed', 'ok']" in text
    assert "attempt 2 fixed it" in text, "the LAST attempt's stdout is logged"
    assert "mode/trigger:" in text


def test_run_log_paper_revise_written_on_exhaustion():
    with temp_project(with_tex=True) as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                                  DANUS_WRITE_PAPER_COMPILE_ATTEMPTS="2"):
        broken = _reviser_edit(replace="\\foo\n\\end{document}", summary="tried")
        with _fake_codex(stdout=broken, returncode=0), \
                _fake_compile([{"ok": False, "log": "! LaTeX Error: boom"}]):
            out = server.paper_revise(compile_log="! initial error")
        assert out["status"] == "compile_failed"
        text = _read_run_log(out)
    assert "compile: failed" in text and "compile_attempts: 2" in text
    assert "boom" in text


def test_run_log_disabled_yields_none_and_tool_still_works():
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     DANUS_WRITE_PAPER_RUN_LOG="0"), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        out = server.paper_write()
        assert out["status"] == "ok", "the tool still works with logging off"
        assert out["log_path"] is None, "no log_path when DANUS_WRITE_PAPER_RUN_LOG=0"
        runs = Path(pdir) / "paper" / ".runs"
        assert not runs.exists() or not any(runs.iterdir()), "no run log written when disabled"


def test_run_log_carries_no_secrets():
    # The prompt is fed to codex over STDIN (argv carries no prompt/secret), so an
    # API key placed in the ENV must never appear in the log.
    fake_key = "sk-ant-SECRETKEY-DO-NOT-LOG-0123456789abcdef"
    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None,
                                     ANTHROPIC_API_KEY=fake_key, OPENAI_API_KEY=fake_key), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0, stderr="ok"):
        out = server.paper_write()
        text = _read_run_log(out)
    assert fake_key not in text, "an API key must never appear in the run log"


def test_run_log_writer_failure_is_isolated():
    # A logging failure must NEVER break the tool: make _write_run_log's mkdir raise
    # for the .runs dir; the tool still returns normally with log_path None.
    orig = Path.mkdir

    def boom(self, *a, **k):
        if ".runs" in str(self):
            raise OSError("run dir is unwritable")
        return orig(self, *a, **k)

    with temp_project() as pdir, env(DANUS_PROJECT_DIR=str(pdir), DANUS_AGENTS_ROOT=None), \
            _fake_codex(stdout=_GOOD_TEX, returncode=0):
        Path.mkdir = boom
        try:
            out = server.paper_write()
        finally:
            Path.mkdir = orig
        assert out["status"] == "ok", "a logging failure must not fail the tool"
        assert out["log_path"] is None, "log_path is None when the writer failed"
        assert Path(out["tex_path"]).exists(), "the paper was still written"


def main() -> None:
    test_paper_write_success_writes_tex_and_parses_gaps()
    print("  [ok] paper_write success -> writes main.tex, parses [GAP:], small dict")
    test_paper_write_reports_resolved_headline_from_brief()
    print("  [ok] paper_write reports the brief-resolved headline (source=brief)")
    test_paper_write_needs_target_when_brief_blank_and_no_target_md()
    print("  [ok] paper_write refuses with needs_target when the target is unset (no main.tex)")
    test_paper_write_reads_target_md_when_brief_blank()
    print("  [ok] paper_write reads <project>/TARGET.md when brief blank (source=target)")
    test_paper_write_explicit_headline_arg_overrides_brief()
    print("  [ok] paper_write explicit headline arg overrides the brief (source=arg)")
    test_paper_write_nonzero_exit_is_honest_and_writes_nothing()
    print("  [ok] paper_write nonzero exit -> status error, no main.tex (no false success)")
    test_paper_write_empty_stdout_is_honest()
    print("  [ok] paper_write empty stdout -> status error, nothing written")
    test_paper_write_timeout_is_honest()
    print("  [ok] paper_write timeout -> status timeout, nothing written")
    test_paper_write_leak_gate_withholds_tex_with_fake_fact_id()
    print("  [ok] paper_write leak gate -> fake fact_id withheld, status leak, quarantined")
    test_paper_write_leak_gate_allows_paper_vocabulary()
    print("  [ok] paper_write leak gate allows worker/verifier/predecessors (paper vocabulary)")
    test_paper_write_leak_gate_removes_stale_clean_tex()
    print("  [ok] paper_write leak with a pre-existing clean main.tex -> stale file removed")
    test_paper_revise_appends_to_existing_log()
    print("  [ok] paper_revise second round appends to the existing REVISION_LOG")
    test_build_app_registers_all_tools()
    print("  [ok] build_app wires paper_write / reference_audit / reference_verify / paper_revise / paper_verify_math")
    test_main_module_runs_build_app()
    print("  [ok] __main__ builds the app and calls run() once")
    test_per_service_model_effort_are_independent()
    print("  [ok] DANUS_WRITE_PAPER_* vs DANUS_HUMAN_SUMMARY_* independent; both fall back to DANUS_CODEX_*")
    test_reference_audit_returns_findings_and_writes_no_tex()
    print("  [ok] reference_audit -> findings returned, main.tex untouched")
    test_reference_audit_nonzero_is_honest()
    print("  [ok] reference_audit nonzero -> status error, empty findings")
    test_paper_revise_overwrites_and_appends_log()
    print("  [ok] paper_revise -> overwrites main.tex + appends REVISION_LOG.md")
    test_paper_revise_nonzero_does_not_overwrite()
    print("  [ok] paper_revise nonzero -> no overwrite, no log entry")
    test_paper_revise_leak_gate_withholds_leaky_revision()
    print("  [ok] paper_revise leak gate -> leaky revision withheld, main.tex untouched, no log")
    test_paper_revise_log_carries_reviser_summary_not_stub()
    print("  [ok] paper_revise -> REVISION_LOG body is the reviser's real summary, not a stub")
    test_paper_revise_degraded_when_no_summary_section()
    print("  [ok] paper_revise -> missing REVISION_SUMMARY degrades honestly, tex still written")
    test_paper_revise_compile_loop_retries_then_succeeds()
    print("  [ok] paper_revise compile loop -> retries with failing log, then succeeds (attempts>1)")
    test_paper_revise_compile_loop_exhausts_and_quarantines()
    print("  [ok] paper_revise compile loop exhausted -> compile_failed, main.tex kept, quarantined")
    test_paper_revise_engine_missing_skips_compile_and_writes_once()
    print("  [ok] paper_revise engine missing -> compile skipped, written once, no loop")
    test_paper_revise_nonzero_writes_nothing_regression()
    print("  [ok] paper_revise nonzero exit -> nothing written, compile not run (regression)")
    test_paper_revise_citation_fixes_threaded_to_prompt()
    print("  [ok] paper_revise citation_fixes -> threaded to reviser prompt, MODE targeted-notes")
    test_run_log_paper_write_success_captures_prompt_stdout_decisions()
    print("  [ok] run log: paper_write success captures prompt + full stdout + decisions + envelope")
    test_run_log_captures_full_stderr_not_just_tail()
    print("  [ok] run log: FULL stderr (>2000 chars) captured, envelope keeps only the tail")
    test_run_log_written_on_failure_nonzero()
    print("  [ok] run log: written on a nonzero codex exit (failure captured)")
    test_run_log_written_on_timeout_raises()
    print("  [ok] run log: written on a codex timeout")
    test_run_log_paper_write_needs_target_early_return()
    print("  [ok] run log: paper_write needs_target early return logs '(no prompt)'/'(no codex run)'")
    test_run_log_reference_audit()
    print("  [ok] run log: reference_audit logs findings + findings_len")
    test_run_log_reference_verify_applied_verdicts()
    print("  [ok] run log: reference_verify logs applied verdict keys + networked=True")
    test_run_log_paper_revise_records_compile_attempts()
    print("  [ok] run log: paper_revise logs ONCE per call with per-attempt compile outcomes")
    test_run_log_paper_revise_written_on_exhaustion()
    print("  [ok] run log: paper_revise compile exhaustion logged (compile failed)")
    test_run_log_disabled_yields_none_and_tool_still_works()
    print("  [ok] run log: DANUS_WRITE_PAPER_RUN_LOG=0 -> log_path None, tool still works")
    test_run_log_carries_no_secrets()
    print("  [ok] run log: no API-key-shaped secret appears in the log")
    test_run_log_writer_failure_is_isolated()
    print("  [ok] run log: a writer failure is isolated (log_path None, tool returns normally)")
    test_reference_verify_writes_ledger_on_ok_never_main_tex()
    print("  [ok] reference_verify ok -> writes ledger (verified-by: verifier), never main.tex")
    test_reference_verify_nonzero_writes_nothing()
    print("  [ok] reference_verify nonzero -> writes nothing (honesty gate)")
    test_reference_verify_empty_stdout_writes_nothing()
    print("  [ok] reference_verify empty stdout -> writes nothing")
    test_reference_verify_timeout_writes_nothing()
    print("  [ok] reference_verify timeout -> writes nothing")
    test_reference_verify_web_unreachable_all_unverifiable_no_false_promotion()
    print("  [ok] reference_verify degraded -> all unverifiable, no false promotion")
    test_reference_verify_uses_networked_path()
    print("  [ok] reference_verify drives codex over the NETWORKED path (role=verifier)")
    test_project_resolution_by_name()
    print("  [ok] project resolution by name + path-escape validation")
    print("ALL SERVER TESTS PASSED")


if __name__ == "__main__":
    main()
