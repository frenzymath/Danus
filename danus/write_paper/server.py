"""write-paper — the write-paper skill's MCP service (role-gated: main only).

Wraps the four paper roles (writer / auditor / verifier / reviser) behind hard-coded
MCP tools so the main agent invokes them with **structured args** (never a
hand-assembled prompt): the large bytes (style guide + fact-graph content) are
assembled inside the tool (``assemble.py``) and never pass through the main
agent's context, and each role's codex runs isolated by construction
(``driver.py`` — empty cwd + fully-embedded prompt). The reference chain is
``auditor (offline, flags) -> verifier (online, checks) -> reviser (edits)`` —
symmetric to the proving chain ``worker -> verifier -> fact_graph``. Only
``reference_verify`` runs codex over the NETWORKED path (gateway
``search_arxiv_theorems`` + web_search, ``DANUS_ROLE=verifier`` minimum privilege);
the other three stay offline.

Tool returns are **small and honest**: paths + status + flags, never the full
``.tex``. ``status`` reflects codex's returncode/stderr/stdout — never ``ok`` on
a nonzero exit, empty stdout, or timeout.

Config resolution (env read at CALL time):
  DANUS_AGENTS_ROOT   root holding all projects (<root>/<project>); lets main
                      address any project by name via the ``project`` arg
  DANUS_PROJECT_DIR   fallback project dir when no ``project`` name is given
  DANUS_WRITE_PAPER_SKILL_DIR   the operator-editable fixed files (see assemble.py)
  DANUS_CODEX_BIN     codex binary
  DANUS_WRITE_PAPER_MODEL / DANUS_WRITE_PAPER_EFFORT   per-service codex overrides;
                      fall back to the neutral DANUS_CODEX_MODEL / DANUS_CODEX_EFFORT
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

from danus.authoring import driver
from danus.authoring.common import classify_outcome, leak_findings, resolve_project
from danus.core import FactGraph
from danus.core._util import utc_now

from . import assemble
from . import paper_chunked
from . import paper_math_verify as pmv

_GAP_RE = re.compile(r"\[GAP:[^\]]*\]")

# LEAK CHECK — paper-appropriate tells that pipeline metadata / machinery survived
# into the emitted .tex. NB: unlike human_summary, this set does NOT forbid
# 'worker' / 'verifier' / 'predecessors' — those legitimately appear in real
# math/CS papers, and the paper keeps a predecessor-DAG note for internal \\ref.
_LEAK_PATTERNS = [
    (r"\b[0-9a-f]{16}\b", "16-hex id (fact_id / hash prefix)"),
    (r"(?im)^\s*author:", "'author:' frontmatter line"),
    (r"(?i)\bfact_[a-z0-9_]+", "'fact_' slug / identifier"),
    (r"(?i)\bmaster_guidance\b", "'master_guidance' (strategy-consult machinery)"),
    (r"(?i)\bfact_submit\b", "'fact_submit' (pipeline verb)"),
]


# --------------------------------------------------------------------------- #
# config resolution (env read at call time — testable / reconfigurable)       #
# --------------------------------------------------------------------------- #

def _model() -> str:
    """Per-service model override, else the neutral default: DANUS_WRITE_PAPER_MODEL
    -> DANUS_CODEX_MODEL -> the driver's built-in default."""
    return os.environ.get("DANUS_WRITE_PAPER_MODEL") or driver.default_model()


def _effort() -> str:
    """Per-service effort override, else the neutral default:
    DANUS_WRITE_PAPER_EFFORT -> DANUS_CODEX_EFFORT -> the driver's built-in default."""
    return os.environ.get("DANUS_WRITE_PAPER_EFFORT") or driver.default_effort()


# --------------------------------------------------------------------------- #
# codex driving + honesty                                                     #
# --------------------------------------------------------------------------- #

def _attach_raw(res: Dict[str, Any], cp: Any) -> Dict[str, Any]:
    """Attach the FULL stderr and the codex argv to the classifier's small dict so
    the per-call run log can record them (``classify_outcome`` keeps only a
    ``stderr_tail`` and drops the command). The prompt is passed to codex over STDIN
    (the driver uses ``input=prompt`` with an argv ending in ``-``), so the argv
    carries NO prompt and NO secret — safe to log. ``cp`` is the driver's
    ``CompletedProcess`` on a normal run, or the raised exception on a
    timeout/missing-binary (``TimeoutExpired`` carries ``.cmd``, no ``.stderr``)."""
    res["stderr_full"] = str(getattr(cp, "stderr", "") or "")
    res["cmd"] = getattr(cp, "args", None) or getattr(cp, "cmd", None)
    return res


def _drive(prompt: str, effort: Optional[str] = None) -> Dict[str, Any]:
    """Run the codex driver once and classify the outcome honestly (see
    ``authoring.common.classify_outcome``: ``ok`` needs a zero exit AND non-empty
    stdout; a nonzero exit, timeout, missing binary, or empty output is not
    ``ok``). Also attaches ``stderr_full`` + ``cmd`` for the run log (see
    ``_attach_raw``). ``effort`` overrides the reasoning effort for this call (e.g.
    ``"low"`` for a mechanical compile-fix retry — no reasoning needed)."""
    try:
        cp: Any = driver.run_codex(prompt, model=_model(), effort=effort or _effort())
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        cp = e
    return _attach_raw(classify_outcome(cp, artifact_noun="artifact"), cp)


def _drive_networked(prompt: str) -> Dict[str, Any]:
    """Like ``_drive`` but over the NETWORKED codex path (``driver.run_codex(
    networked=True)``): ``--dangerously-bypass-approvals-and-sandbox`` + the danus
    gateway injected at ``DANUS_ROLE=verifier`` (read-only ``search_arxiv_theorems``,
    minimum privilege) + codex's built-in ``web_search``. Used ONLY by
    ``reference_verify`` — the sole tool that needs live arXiv/web access. Same honesty
    classifier (a nonzero exit / empty stdout / timeout is never ``ok``); also
    attaches ``stderr_full`` + ``cmd`` for the run log."""
    try:
        cp: Any = driver.run_codex(prompt, model=_model(), effort=_effort(),
                                   networked=True, gateway_role="verifier")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        cp = e
    return _attach_raw(classify_outcome(cp, artifact_noun="verdicts"), cp)


# --------------------------------------------------------------------------- #
# per-call diagnostic run log (mirrors the verify service's per-run log.md)    #
# --------------------------------------------------------------------------- #

def _run_log_enabled() -> bool:
    """Whether the per-call diagnostic run log is written. Default ON; opt out with
    ``DANUS_WRITE_PAPER_RUN_LOG=0`` (also ``false`` / ``no``)."""
    return os.environ.get("DANUS_WRITE_PAPER_RUN_LOG", "1").lower() not in ("0", "false", "no")


def _write_run_log(tool: str, project_dir: Any, prompt: Optional[str],
                   res: Optional[Dict[str, Any]], decisions: Dict[str, Any],
                   envelope: Optional[Dict[str, Any]] = None,
                   paper_id: Optional[str] = None) -> Optional[str]:
    """Write a full on-disk diagnostic record for ONE tool call and return its path
    (or ``None`` when disabled / on any failure).

    Mirrors the verify service's per-run ``log.md`` (``danus/verify/launcher.py``):
    the full assembled prompt, codex's FULL stdout AND FULL stderr, the honest
    result, the tool's post-processing decisions, and the small envelope the tool is
    about to return — so the main agent can localize a failure (prompt vs codex vs
    tool logic) without the bytes ever entering its context.

    Written to ``<paper workspace>/.runs/<utc>-<tool>/log.md`` (``<utc>`` = the
    ISO timestamp with ``:`` → ``-`` for a filesystem-safe dir name); the workspace
    is the per-paper dir (default paper → ``<project>/paper/.runs/``).

    **FAILURE-ISOLATED:** the whole body is wrapped in ``try/except`` → returns
    ``None`` on any error. A logging failure must NEVER break the tool — the paper
    (and its honest envelope) is the primary function; the log is a diagnostic aid."""
    if not _run_log_enabled():
        return None
    try:
        res = res or {}
        stamp = utc_now().replace(":", "-")
        run_dir = assemble.paper_workspace(Path(project_dir), paper_id) / ".runs" / f"{stamp}-{tool}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "log.md"

        cmd = res.get("cmd")
        command = " ".join(str(c) for c in cmd) if cmd else "(no codex run)"
        stdout = res.get("stdout", "") or "(empty)"
        stderr = res.get("stderr_full", "") or "(empty)"
        prompt_body = prompt if prompt is not None else (
            "(no prompt — early return before codex was driven)")

        parts: List[str] = []
        parts.append("## Header")
        parts.append(f"- utc: {utc_now()}")
        parts.append(f"- tool: {tool}")
        parts.append(f"- project: {project_dir}")
        parts.append(f"- model: {_model()} / effort: {_effort()}")
        parts.append(f"- networked: {tool == 'reference_verify'}")
        parts.append(f"- command: {command}")

        parts.append("\n## INPUT — assembled prompt\n")
        parts.append(prompt_body)

        parts.append("\n## CODEX OUTPUT — stdout\n")
        parts.append(stdout)

        parts.append("\n## CODEX OUTPUT — stderr\n")
        parts.append(stderr)

        parts.append("\n## RESULT")
        parts.append(f"- status: {res.get('status')}")
        parts.append(f"- returncode: {res.get('returncode')}")
        if res.get("error"):
            parts.append(f"- error: {res.get('error')}")

        parts.append("\n## TOOL DECISIONS")
        for key, value in decisions.items():
            parts.append(f"- {key}: {value}")

        if envelope is not None:
            parts.append("\n## RETURNED ENVELOPE\n")
            parts.append("```json")
            parts.append(json.dumps(envelope, ensure_ascii=False, indent=2, default=str))
            parts.append("```")

        log_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
        return str(log_path)
    except Exception:  # noqa: BLE001 - a logging failure must NEVER break the tool
        return None


def _gaps(tex: str) -> List[str]:
    """Extract every ``[GAP: ...]`` marker the writer left in the tex."""
    return _GAP_RE.findall(tex)


def _keep_swarm_env() -> bool:
    """Env opt-out for the auto-stop: ``DANUS_KEEP_SWARM_ON_WRITE=1`` keeps the
    swarm running while the paper is drafted (the rare 'keep exploring' case)."""
    return os.environ.get("DANUS_KEEP_SWARM_ON_WRITE", "").lower() in ("1", "true", "yes")


def _ensure_swarm_stopped(project: str) -> Dict[str, Any]:
    """Gracefully wind down the project's worker swarm when entering write-paper
    (default behavior): entering write-paper is the operator committing to "the
    problem is proven and this is the answer", so the swarm should stop burning
    codex compute. Graceful (no ``--force``) — never drops an in-flight round's
    verified work. Idempotent (an idle/absent swarm is a no-op).

    **Failure-isolated:** a stop failure is reported, NEVER raised — it must not
    block paper generation (the paper is the primary function). Returns
    ``{"result": <do_stop list>}`` on a stop, ``{"noop": <msg>}`` when there is
    nothing to stop (``do_stop`` raises ``SystemExit`` for an absent swarm — an
    idempotent no-op, not a failure), or ``{"error": "<Type>: <msg>"}`` on any
    other failure. Deferred import avoids an orchestration <-> write_paper import
    cycle."""
    try:
        from danus.orchestration.cli import do_stop
        return {"result": do_stop(project)}  # graceful (force=False)
    except SystemExit as e:
        # do_stop raises SystemExit("no workers for target ...") when there is
        # nothing to stop — an idempotent no-op, not a failure. (SystemExit is not
        # an Exception subclass, so it must be caught explicitly.)
        return {"noop": str(e)}
    except Exception as e:  # noqa: BLE001 - isolate ALL other failures from paper generation
        return {"error": f"{type(e).__name__}: {e}"}



# --------------------------------------------------------------------------- #
# reviser output split + in-tool compile gate (P2/P3)                         #
# --------------------------------------------------------------------------- #

# The reviser's stdout is two literal-separator sections (see PAPER_REVISER_PROMPT
# §1): the full tex, then the round summary. The tool splits on these markers so
# the TOOL (not the reviser) writes REVISION_LOG.md with the reviser's REAL summary.
_MAIN_TEX_SEP = "%%%MAIN_TEX%%%"
_REVISION_SUMMARY_SEP = "%%%REVISION_SUMMARY%%%"

# PATCH contract (the reviser's default output): a set of exact find/replace edits the
# tool applies deterministically to main.tex — so the reviser NEVER has to re-emit the
# whole (possibly >100K-char) paper, which risks truncation / refusal on a large file.
# Each edit is a block; an INSERT is a find/replace whose replacement re-includes the
# anchor. The reviser emits ``%%%PATCH%%%`` then blocks then ``%%%REVISION_SUMMARY%%%``.
_PATCH_SEP = "%%%PATCH%%%"
_PATCH_BLOCK_RE = re.compile(
    r"<<<<<<< FIND\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>> REPLACE", re.DOTALL)


def _split_reviser_patch(stdout: str) -> Tuple[str, Optional[str]]:
    """Split the reviser's PATCH output into ``(patch_text, summary_or_None)`` on
    ``%%%REVISION_SUMMARY%%%``. Everything before it (after an optional ``%%%PATCH%%%``
    header) is the patch blocks; after it is the summary. Missing summary → the whole
    (header-stripped) body is the patch, summary None."""
    if _REVISION_SUMMARY_SEP in stdout:
        patch_part, summary_part = stdout.split(_REVISION_SUMMARY_SEP, 1)
        summary: Optional[str] = summary_part.strip() or None
    else:
        patch_part, summary = stdout, None
    idx = patch_part.find(_PATCH_SEP)
    if idx != -1:
        patch_part = patch_part[idx + len(_PATCH_SEP):]
    return patch_part, summary


def _apply_reviser_patch(base_tex: str, patch_text: str) -> Tuple[str, int, List[str]]:
    """Apply the reviser's find/replace blocks to ``base_tex`` deterministically.
    Returns ``(new_tex, applied_count, errors)``. Each block's FIND must match EXACTLY
    ONCE (a 0- or multi-match block is SKIPPED and reported, never applied blindly) —
    so a patch can never silently corrupt or duplicate. Blocks apply in order."""
    edits = _PATCH_BLOCK_RE.findall(patch_text)
    new = base_tex
    applied = 0
    errors: List[str] = []
    for i, (find, repl) in enumerate(edits, 1):
        if find == "":
            errors.append(f"edit {i}: empty FIND (skipped)")
            continue
        n = new.count(find)
        if n == 1:
            new = new.replace(find, repl, 1)
            applied += 1
        elif n == 0:
            errors.append(f"edit {i}: FIND not found (skipped): {find[:80]!r}")
        else:
            errors.append(f"edit {i}: FIND matches {n}× — not unique (skipped): {find[:80]!r}")
    return new, applied, errors


# The writer optionally appends a provenance map after the tex (see
# PAPER_WRITER_PROMPT §3): `%%%PROVENANCE%%%\n{label -> source_fact id}`. The tool
# splits it off BEFORE the leak gate (so provenance fact ids never trip the gate),
# writes it to a side .provenance.json (never shipped), and paper_verify_math
# consumes it as optional enrichment.
_PROVENANCE_SEP = "%%%PROVENANCE%%%"


_FENCE_OPEN_RE = re.compile(r"^```[^\n]*\n")


def _strip_code_fence(s: str) -> str:
    """Defensively remove a wrapping markdown code fence (```` ```tex … ``` ````).
    The writer/reviser contract is raw LaTeX, but a model sometimes wraps its whole
    output in a fence — and a leading ```` ```tex ```` line breaks the compile
    ('Missing \\begin{document}'). If the (newline-trimmed) text starts with a
    ```` ```lang ```` line, drop that opening line and a matching trailing ```` ``` ````;
    otherwise return the text unchanged. Only an OUTER wrapping fence is stripped —
    real LaTeX never begins with ```` ``` ````, so this cannot corrupt a clean file."""
    t = s.strip("\n")
    m = _FENCE_OPEN_RE.match(t)
    if not m:
        return s
    t = t[m.end():]
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3].rstrip("\n")
    return t + "\n"


def _split_provenance(stdout: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Split the writer's stdout into ``(tex, provenance_map_or_None)``. Everything
    before ``%%%PROVENANCE%%%`` is the tex (what the leak gate + main.tex see);
    after it is a JSON ``{label: fact_id}`` map (fact ids allowed — it is a side
    file, not the paper). No marker / malformed JSON / non-dict → ``(stdout, None)``
    (backward-compatible: a plain-tex writer output is unchanged)."""
    if _PROVENANCE_SEP not in stdout:
        return stdout, None
    tex_part, prov_part = stdout.split(_PROVENANCE_SEP, 1)
    try:
        data = json.loads(prov_part.strip())
    except (json.JSONDecodeError, ValueError):
        return tex_part, None
    return tex_part, (data if isinstance(data, dict) else None)


def _write_provenance(project_dir: Any, paper_id: Optional[str],
                      provenance: Optional[Dict[str, Any]]) -> Optional[str]:
    """Write the writer's ``{label: source_fact id}`` map to
    ``<paper workspace>/.provenance.json`` (a side file ``paper_verify_math``
    optionally consumes; NEVER shipped, NEVER leak-checked). Returns the path str,
    or ``None`` when there is nothing to write. Failure-isolated — a write failure
    must not break paper generation."""
    if not provenance:
        return None
    try:
        path = assemble.paper_workspace(Path(project_dir), paper_id) / ".provenance.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:  # noqa: BLE001 - a provenance write failure never breaks the paper
        return None


def _split_reviser_output(stdout: str) -> Tuple[str, Optional[str]]:
    """Split the reviser's stdout into ``(tex, summary_or_None)``.

    Contract: ``%%%MAIN_TEX%%%\\n<tex>\\n%%%REVISION_SUMMARY%%%\\n<summary>``.
    Everything between the (optional) ``%%%MAIN_TEX%%%`` header and
    ``%%%REVISION_SUMMARY%%%`` is the tex; everything after the summary separator is
    the summary. If the ``%%%REVISION_SUMMARY%%%`` separator is ABSENT → honest
    degradation: the whole stdout (minus an optional leading ``%%%MAIN_TEX%%%``
    header) is treated as the tex, and ``summary=None`` (the caller records the
    degradation in the log). The tex is stripped of a leading ``%%%MAIN_TEX%%%``
    header line only; its body is otherwise returned verbatim."""
    if _REVISION_SUMMARY_SEP in stdout:
        tex_part, summary_part = stdout.split(_REVISION_SUMMARY_SEP, 1)
        summary: Optional[str] = summary_part.strip() or None
    else:
        tex_part, summary = stdout, None
    tex = _strip_main_tex_header(tex_part)
    return tex, summary


def _strip_main_tex_header(tex_part: str) -> str:
    """Drop a single leading ``%%%MAIN_TEX%%%`` header line (with its trailing
    newline) if present; otherwise return the text unchanged. The tex body itself
    is never otherwise altered."""
    idx = tex_part.find(_MAIN_TEX_SEP)
    if idx != -1:
        after = tex_part[idx + len(_MAIN_TEX_SEP):]
        # drop the rest of the header line (up to and including its newline)
        nl = after.find("\n")
        return after[nl + 1:] if nl != -1 else after
    return tex_part


def _compile_attempts() -> int:
    """The in-tool compile-retry cap: ``DANUS_WRITE_PAPER_COMPILE_ATTEMPTS`` (env),
    fallback 3. A non-positive / unparseable value falls back to 3."""
    raw = os.environ.get("DANUS_WRITE_PAPER_COMPILE_ATTEMPTS", "")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 3
    return n if n > 0 else 3


def _compile_fix_effort() -> str:
    """Reasoning effort for a compile-FIX retry — a mechanical, local edit that needs
    no math reasoning, so it defaults to ``low`` (fast). Override with
    ``DANUS_WRITE_PAPER_COMPILE_EFFORT``."""
    return os.environ.get("DANUS_WRITE_PAPER_COMPILE_EFFORT", "low")


def _compile_fix_prompt(tex: str, compile_log: str) -> str:
    """A LIGHTWEIGHT compile-fix prompt: fix ONLY the compile error(s) in the given
    (already-substantively-revised) tex, as a small PATCH — not a full re-emit. The
    task is mechanical (a double subscript, an undeclared macro, an unbalanced
    delimiter/environment), so it runs at low effort. Output the ``%%%PATCH%%%``
    find/replace contract so the tool applies it deterministically (re-emitting the
    whole file risks truncation)."""
    return (
        "You are fixing LaTeX COMPILE ERRORS in a mathematics paper. Emit the MINIMAL "
        "edits to fix ONLY the compile error(s) below — change nothing else. Output "
        "ONLY a patch of exact find/replace edits in this contract:\n"
        "%%%PATCH%%%\n<<<<<<< FIND\n<exact snippet copied verbatim from the file, "
        "including enough surrounding text to be UNIQUE>\n=======\n<the corrected "
        "snippet>\n>>>>>>> REPLACE\n(repeat one block per fix)\n%%%REVISION_SUMMARY%%%\n"
        "<one line naming what you fixed>\n\nCommon causes: a double subscript "
        "(`x_a_b` -> `x_{a,b}`), an undeclared macro/operator (declare it in the "
        "preamble), an unbalanced/stray brace, delimiter, or environment.\n\n"
        "=== COMPILE OUTPUT (the failing pdflatex/tectonic log; `l.NNN` marks the "
        "offending line/macro) ===\n" + (compile_log or "").rstrip()
        + "\n\n=== CURRENT main.tex (find the offending snippets here) ===\n" + tex
    )


def _compile_verify_script() -> Path:
    """Locate the shipped ``driver/compile_verify.sh`` (the main-agent skill half).
    Resolved at CALL time (not import) so the layout stays overridable."""
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / ".claude" / "skills" / "write-paper" / "driver" / "compile_verify.sh"


def _compile_check(tex: str) -> Dict[str, Any]:
    """Compile-gate the tex OUTSIDE the reviser (the compile is the tool's gate, not
    the reviser's self-check). Writes ``tex`` to a temp ``main.tex`` and runs
    ``driver/compile_verify.sh`` on it, returning
    ``{"ok": bool, "log": str, "engine_available": bool}``.

    ``compile_verify.sh`` exits 3 when the LaTeX engine (pdflatex) is missing → we
    report ``engine_available=False`` (and ``ok=False``) so the caller does NOT loop
    and does NOT gate on something it cannot run. A clean compile → ``ok=True``. Any
    other nonzero exit → ``ok=False`` with the combined stdout/stderr as ``log``.

    Factored behind this single function so the offline tests mock it (no real
    pdflatex needed)."""
    script = _compile_verify_script()
    with tempfile.TemporaryDirectory(prefix="wp_compile_check_") as d:
        tex_path = Path(d) / "main.tex"
        tex_path.write_text(tex, encoding="utf-8")
        try:
            cp = subprocess.run(
                ["bash", str(script), str(tex_path)],
                capture_output=True, text=True,
            )
        except (FileNotFoundError, OSError) as e:
            # bash / the script itself is missing — treat as engine-unavailable so
            # we degrade honestly rather than loop forever.
            return {"ok": False, "log": f"compile_check could not run: {e}", "engine_available": False}
        log = (cp.stdout or "") + (cp.stderr or "")
        if cp.returncode == 3:
            return {"ok": False, "log": log, "engine_available": False}
        return {"ok": cp.returncode == 0, "log": log, "engine_available": True}


def _log_tail(text: str, max_chars: int = 4000) -> str:
    """The trailing ``max_chars`` of a compile log (the failing lines are at the
    end); prefixed with an elision marker when truncated."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    return "… (log head truncated)\n" + text[-max_chars:]


# --------------------------------------------------------------------------- #
# tools                                                                       #
# --------------------------------------------------------------------------- #

def _paper_write_chunked(pdir: Path, resolved: List[str], source: str,
                         paper_id: Optional[str], swarm_stop: Dict[str, Any],
                         prompt_chars: int, budget: int,
                         fact_ids: Optional[List[str]] = None,
                         instructions: Optional[str] = None,
                         fact_id_warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """The CHUNKED ``paper_write`` path: used when the single-pass writer
    prompt would overflow the model window (``prompt_chars > budget``). Runs the
    three-phase generation (``paper_chunked.generate``: plan -> per-section fill ->
    stitch), then re-uses the SAME downstream as the single-pass path — leak-gate the
    STITCHED whole, quarantine on a hit (never overwrite main.tex), write main.tex,
    split/write the merged provenance, and log — returning the same envelope shape
    plus ``chunked: True`` and ``sections: <n>``.

    HONESTY: if the planner or ANY section writer returns non-ok, or the coverage
    check fails, generation fails honestly — no main.tex is written, and the failing
    phase is reported (``status='chunk_failed'``, ``failed_phase=<phase>``)."""
    ws = assemble.paper_workspace(pdir, paper_id)
    tex_path = ws / "main.tex"
    base: Dict[str, Any] = {
        "tex_path": str(tex_path),
        "headline": resolved,
        "headline_source": source,
        "paper_id": paper_id,
        "swarm_stop": swarm_stop,
        "chunked": True,
        "chunk_chars": prompt_chars,
        "chunk_budget": budget,
        "selected_facts": len(fact_ids) if fact_ids else 0,
        "fact_id_warnings": fact_id_warnings or [],
        "gaps": [],
        "leak_findings": [],
    }
    gen = paper_chunked.generate(pdir, headline=resolved, paper_id=paper_id, drive=_drive,
                                 fact_ids=fact_ids, instructions=instructions)

    if not gen.get("ok"):
        # planner/section non-ok OR coverage/parse failure → honest abort, no tex.
        out = dict(base)
        out["status"] = "chunk_failed"
        out["failed_phase"] = gen.get("phase")
        out["error"] = gen.get("error")
        out["sections"] = gen.get("sections", 0)
        out["stderr_tail"] = (gen.get("res") or {}).get("stderr_tail", "")
        out["log_path"] = _write_run_log(
            "paper_write", pdir, gen.get("prompt"), gen.get("res"),
            {"chunked": True, "failed_phase": gen.get("phase"),
             "chunk_error": gen.get("error"), "phase_logs": gen.get("phase_logs"),
             "chunk_chars": prompt_chars, "chunk_budget": budget,
             "headline": resolved, "headline_source": source, "swarm_stop": swarm_stop},
            envelope=out, paper_id=paper_id)
        return out

    # SUCCESS from generation → same downstream as single-pass: leak-gate the
    # STITCHED whole, then write / provenance / log. The stitch is deterministic
    # Python, so there is no codex `res` for this final write; the per-phase codex
    # runs were logged inside generate()'s phase_logs (recorded below).
    tex = gen["tex"]
    provenance = gen.get("provenance")
    n_sections = gen.get("sections", 0)
    leaks = leak_findings(tex, _LEAK_PATTERNS)
    out = dict(base)
    out["sections"] = n_sections
    out["leak_findings"] = leaks
    out["returncode"] = 0
    out["stderr_tail"] = ""
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    if leaks:
        # A leaked id in ANY section → quarantine the whole stitched paper; never
        # overwrite main.tex. (The leak gate runs on the STITCHED whole, so a leak
        # anywhere in any section is caught.)
        leaky_path = tex_path.with_name("main.leaky.tex")
        leaky_path.write_text(tex, encoding="utf-8")
        if tex_path.exists():
            tex_path.unlink()
        out["status"] = "leak"
        out["error"] = "paper contains leaked identifiers/machinery; not kept as main.tex"
        out["leaky_tex_path"] = str(leaky_path)
        out["gaps"] = _gaps(tex)
        out["log_path"] = _write_run_log(
            "paper_write", pdir, None, None,
            {"chunked": True, "sections": n_sections, "phase_logs": gen.get("phase_logs"),
             "chunk_chars": prompt_chars, "chunk_budget": budget,
             "leak_findings": leaks, "gaps": out["gaps"],
             "headline": resolved, "headline_source": source, "swarm_stop": swarm_stop},
            envelope=out, paper_id=paper_id)
        return out
    tex_path.write_text(tex, encoding="utf-8")
    out["status"] = "ok"
    out["gaps"] = _gaps(tex)
    prov_written = _write_provenance(pdir, paper_id, provenance)
    out["provenance_path"] = prov_written
    out["log_path"] = _write_run_log(
        "paper_write", pdir, None, None,
        {"chunked": True, "sections": n_sections, "phase_logs": gen.get("phase_logs"),
         "chunk_chars": prompt_chars, "chunk_budget": budget,
         "leak_findings": leaks, "gaps": out["gaps"], "provenance_path": prov_written,
         "headline": resolved, "headline_source": source, "swarm_stop": swarm_stop},
        envelope=out, paper_id=paper_id)
    return out


def paper_write(project: Optional[str] = None,
                headline: Optional[List[str]] = None,
                stop_workers: bool = False,
                paper_id: Optional[str] = None,
                fact_ids: Optional[List[str]] = None,
                instructions: Optional[str] = None) -> Dict[str, Any]:
    """Write the first complete ``main.tex`` for a project from its verified fact
    graph, house style, and structure plan. Assembles the writer prompt (facts +
    style + structure + brief + ledger, all embedded — nothing enters your
    context), drives a local codex, and writes the emitted LaTeX to the paper's
    workspace ``main.tex`` (default paper → ``<project>/paper/main.tex``; a
    non-default ``paper_id`` → ``<project>/papers/<paper_id>/main.tex``).

    **Fact selection (``fact_ids``) — the main-agent curation seam.** Read the
    compact ``paper_subgraph`` skeleton first, then pass the load-bearing subset you
    choose to PRESENT as ``fact_ids``: only those facts are embedded in FULL, plus
    their direct-predecessor STATEMENTS as ``\\ref``/``\\cite`` context (never
    re-proved). This mirrors how a real paper writes up its main results and cites
    its granular lemmas — and is what keeps a large project's paper inside one
    context window (the whole transitive closure would overflow). Omit ``fact_ids``
    (``None``) → the legacy whole-closure embedding, unchanged. Unknown ids →
    ``status='bad_fact_ids'`` (no paper); ids outside the target closure are kept but
    surfaced in ``fact_id_warnings``.

    **``instructions`` — your editorial direction** (sectioning, emphasis, what to
    foreground), embedded verbatim as an authoritative ``MAIN_AGENT_INSTRUCTIONS``
    block. A plain string; carries no fact ids into the .tex.

    ``paper_id`` selects WHICH paper in the project (multiple papers per project;
    one fact graph). None / "" / the default slug maps to the LEGACY single-paper
    workspace; any other id opens an isolated ``papers/<paper_id>/`` workspace with
    its own brief / ledger / TARGET.md / main.tex — so N papers never collide.

    ``headline`` selects the paper's TARGET fact ids. When omitted it flows through
    ``assemble.resolve_headline`` — an explicit arg wins (``source='arg'``), else
    the brief's ``headline_fact_ids`` field (``'brief'``), else the finalized
    ``<project>/TARGET.md`` written by ``danus finalize`` (``'target'``). If NONE of
    these is set the target is UNSET and this tool REFUSES to guess: it returns
    ``{status: 'needs_target', message, candidates}`` (the terminal-fact
    suggestions) and writes NO ``main.tex`` — run ``danus finalize <project>
    <fact_id>`` or set ``headline_fact_ids`` in the brief. Only the target's
    transitive-predecessor closure is embedded, in topological order, with zero
    invention — so proven-but-unused side lemmas are excluded and the writer's
    facts match the ledger's closure.

    Does NOT compile — the compile gate stays ``compile_verify.sh`` (main-agent,
    SKILL step 3).

    **Side effect (default OFF): optionally stops the project's worker swarm.**
    Entering write-paper does NOT necessarily mean the whole problem is proven — a
    *partial* result may be written up while the swarm keeps exploring the rest — so
    the tool never force-stops the workers on its own. The **main agent decides**:
    it surfaces the fork to the operator at the start of write-paper and, on "stop",
    calls ``paper_write(stop_workers=True)`` (or ``danus stop``). With
    ``stop_workers=True`` the stop runs once the target is resolved (after the
    ``needs_target`` refusal), before drafting; it is graceful (never drops an
    in-flight verified round), idempotent, and failure-isolated (a stop failure is
    reported in ``swarm_stop``, never blocks the paper). ``DANUS_KEEP_SWARM_ON_WRITE=1``
    forces the keep-running behavior even if a caller passes ``stop_workers=True``.

    Returns ``{tex_path, status, returncode, headline, headline_source, swarm_stop,
    gaps, leak_findings, stderr_tail, log_path}``; ``headline`` is the resolved target ids
    actually used and ``headline_source`` records where they came from (``arg`` /
    ``brief`` / ``target``); ``swarm_stop`` is ``{result|error|skipped}``. On any
    non-``ok`` status the tex is NOT written. A LEAK CHECK (AGENTS.md invariant #6 —
    no leaked pipeline internals) runs on the emitted .tex: if it contains a machinery tell (a 16-hex fact_id, an
    ``author:`` line, a ``fact_`` slug, ``master_guidance`` / ``fact_submit``) the
    output is quarantined to ``main.leaky.tex`` and ``main.tex`` is not written
    (``status='leak'``)."""
    pdir = resolve_project(project)
    ws = assemble.paper_workspace(pdir, paper_id)
    tex_path = ws / "main.tex"
    resolved, source = assemble.resolve_headline(pdir, headline, paper_id)
    if source == "unset":
        # The target is not recorded — refuse to guess. Suggest the terminal facts
        # so the operator can `danus finalize` one, and write NO main.tex.
        candidates = assemble._terminal_facts(FactGraph(pdir))
        out = {
            "tex_path": str(tex_path),
            "status": "needs_target",
            "headline": [],
            "headline_source": source,
            "paper_id": paper_id,
            "message": ("no paper target is set — run `danus finalize <project> "
                        "[--paper <paper_id>] <fact_id>` to record it, or set "
                        "headline_fact_ids in the project brief; write-paper will not guess"),
            "candidates": candidates,
        }
        out["log_path"] = _write_run_log(
            "paper_write", pdir, None, None,
            {"needs_target": True, "candidates_count": len(candidates)},
            envelope=out, paper_id=paper_id)
        return out
    # Validate a main-agent SELECTION (fact_ids) once the target is known: unknown
    # ids are a hard refusal (no paper); ids outside the target closure are kept but
    # surfaced as a warning (the main agent's editorial judgment, not an error).
    fact_id_warnings: List[str] = []
    if fact_ids:
        known = set(FactGraph(pdir).list())
        unknown = [f for f in fact_ids if f not in known]
        if unknown:
            out = {
                "tex_path": str(tex_path),
                "status": "bad_fact_ids",
                "headline": resolved,
                "headline_source": source,
                "paper_id": paper_id,
                "selected_facts": len(fact_ids),
                "unknown_fact_ids": unknown,
                "message": (f"{len(unknown)} selected fact id(s) are not in the fact "
                            "graph — check paper_subgraph output; no main.tex written"),
            }
            out["log_path"] = _write_run_log(
                "paper_write", pdir, None, None,
                {"bad_fact_ids": unknown}, envelope=out, paper_id=paper_id)
            return out
        try:
            closure = set(assemble.closure_order(pdir, resolved, paper_id))
            outside = [f for f in fact_ids if f not in closure]
            if outside:
                fact_id_warnings.append(
                    f"{len(outside)} selected fact(s) are outside the target closure "
                    f"(kept anyway): {outside}")
        except assemble.TargetUnsetError:
            pass  # unreachable here (source != unset), but never let this block the paper
    # Entering write-paper is the "answer is confirmed" commit point — gracefully
    # stop the swarm by default (idempotent, failure-isolated; never blocks the
    # paper). Placed AFTER the needs_target refusal so we only wind the swarm down
    # once we are actually producing the paper. Opt out with stop_workers=False or
    # DANUS_KEEP_SWARM_ON_WRITE=1.
    if stop_workers and not _keep_swarm_env():
        swarm_stop: Dict[str, Any] = _ensure_swarm_stopped(project or pdir.name)
    else:
        swarm_stop = {"skipped": "stop_workers=False" if not stop_workers
                      else "DANUS_KEEP_SWARM_ON_WRITE"}
    # THRESHOLD: only chunk when the would-be single-pass writer prompt would
    # overflow the model window. With a main-agent SELECTION (fact_ids) the estimate
    # is the CURATED prompt, so chunking is the EXTREME fallback (fires only if even
    # the selected subset overflows); under budget → the single-pass path, unchanged.
    over, prompt_chars, budget = paper_chunked.should_chunk(
        pdir, resolved, paper_id, fact_ids=fact_ids, instructions=instructions)
    if over:
        return _paper_write_chunked(pdir, resolved, source, paper_id, swarm_stop,
                                    prompt_chars, budget, fact_ids=fact_ids,
                                    instructions=instructions,
                                    fact_id_warnings=fact_id_warnings)
    prompt = assemble.build_prompt("writer", pdir, headline=resolved, paper_id=paper_id,
                                   fact_ids=fact_ids, instructions=instructions)
    res = _drive(prompt)
    out: Dict[str, Any] = {
        "tex_path": str(tex_path),
        "status": res["status"],
        "returncode": res["returncode"],
        "headline": resolved,
        "headline_source": source,
        "paper_id": paper_id,
        "swarm_stop": swarm_stop,
        "selected_facts": len(fact_ids) if fact_ids else 0,
        "fact_id_warnings": fact_id_warnings,
        "gaps": [],
        "leak_findings": [],
        "stderr_tail": res["stderr_tail"],
    }
    if res["status"] != "ok":
        out["error"] = res.get("error")
        out["log_path"] = _write_run_log(
            "paper_write", pdir, prompt, res,
            {"headline": resolved, "headline_source": source, "swarm_stop": swarm_stop,
             "leak_findings": out["leak_findings"], "gaps": out["gaps"]},
            envelope=out, paper_id=paper_id)
        return out
    tex, provenance = _split_provenance(_strip_code_fence(res["stdout"]))
    leaks = leak_findings(tex, _LEAK_PATTERNS)
    out["leak_findings"] = leaks
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    if leaks:
        # DO NOT keep a .tex that leaked pipeline metadata under the clean name.
        # Quarantine it for inspection and report an honest non-ok status.
        leaky_path = tex_path.with_name("main.leaky.tex")
        leaky_path.write_text(tex, encoding="utf-8")
        if tex_path.exists():
            tex_path.unlink()  # never leave a stale clean .tex next to a leaky run
        out["status"] = "leak"
        out["error"] = "paper contains leaked identifiers/machinery; not kept as main.tex"
        out["leaky_tex_path"] = str(leaky_path)
        out["gaps"] = _gaps(tex)
        out["log_path"] = _write_run_log(
            "paper_write", pdir, prompt, res,
            {"headline": resolved, "headline_source": source, "swarm_stop": swarm_stop,
             "leak_findings": leaks, "gaps": out["gaps"]},
            envelope=out, paper_id=paper_id)
        return out
    tex_path.write_text(tex, encoding="utf-8")
    out["gaps"] = _gaps(tex)
    # Provenance (label -> source_fact id) goes to a SIDE file, out-of-band, so it
    # never touches the leak-gated .tex; paper_verify_math consumes it (optional
    # enrichment). Only the clean-tex success path writes it.
    prov_written = _write_provenance(pdir, paper_id, provenance)
    out["provenance_path"] = prov_written
    out["log_path"] = _write_run_log(
        "paper_write", pdir, prompt, res,
        {"headline": resolved, "headline_source": source, "swarm_stop": swarm_stop,
         "leak_findings": leaks, "gaps": out["gaps"], "provenance_path": prov_written},
        envelope=out, paper_id=paper_id)
    return out


def paper_subgraph(project: Optional[str] = None,
                   headline: Optional[List[str]] = None,
                   paper_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a COMPACT, deterministic skeleton of the paper's target-fact closure
    for YOU (the main agent) to read and SELECT from — statements only, no proofs,
    no codex, no writes.

    This is the curation seam. The whole transitive closure's full proofs overflow a
    single writer pass on a large project; but v2-style single-pass writing works
    when the main agent (no reading bottleneck) picks the load-bearing subset. Read
    this skeleton, choose the facts to PRESENT, then call
    ``paper_write(fact_ids=[...], instructions="...")`` — only those facts are
    embedded in full, their granular predecessors become ``\\ref``/``\\cite`` context.

    Each fact record is ``{id, statement (one-line), predecessors (in-closure DAG
    edges), dependents (in-closure in-degree — higher = more load-bearing),
    glossary_introduces (symbols it introduces)}``, in topological order
    (predecessors first) — the SAME closure/order the writer would embed.

    The target is the RECORDED headline (arg > brief > TARGET.md, via
    ``resolve_headline``). Unset → ``status='needs_target'`` (same refusal as
    ``paper_write``). Returns ``{status, headline, headline_source, count, facts,
    paper_id}``. Deterministic + side-effect-free (no codex, no run log)."""
    pdir = resolve_project(project)
    resolved, source = assemble.resolve_headline(pdir, headline, paper_id)
    if source == "unset":
        candidates = assemble._terminal_facts(FactGraph(pdir))
        return {
            "status": "needs_target",
            "headline": [],
            "headline_source": source,
            "paper_id": paper_id,
            "count": 0,
            "facts": [],
            "message": ("no paper target is set — run `danus finalize <project> "
                        "[--paper <paper_id>] <fact_id>` to record it, or set "
                        "headline_fact_ids in the project brief"),
            "candidates": candidates,
        }
    skel = assemble.subgraph_skeleton(pdir, resolved, paper_id)
    return {
        "status": "ok",
        "headline": resolved,
        "headline_source": source,
        "paper_id": paper_id,
        "count": skel["count"],
        "facts": skel["facts"],
    }


def reference_audit(project: Optional[str] = None,
                paper_id: Optional[str] = None) -> Dict[str, Any]:
    """Audit the paper's bibliography: the auditor reads ONLY ``main.tex`` + the
    reference ledger (no facts, no style guide) and **flags** entries it cannot
    vouch for — it has no tools and no network. The ONLINE verification of the
    flags is ``reference_verify``'s job (the reference verifier: networked codex,
    gateway ``search_arxiv_theorems`` + web_search); the auditor only flags. Writes
    NO ``main.tex``. Returns ``{findings, ledger_path, status, returncode, log_path}`` where
    ``findings`` is the auditor's report text (small) — feed it to ``reference_verify``."""
    pdir = resolve_project(project)
    ledger_path = assemble.paper_workspace(pdir, paper_id) / "REFERENCE_LEDGER.md"
    prompt = assemble.build_prompt("auditor", pdir, paper_id=paper_id)
    res = _drive(prompt)
    out: Dict[str, Any] = {
        "findings": res["stdout"] if res["status"] == "ok" else "",
        "ledger_path": str(ledger_path),
        "status": res["status"],
        "returncode": res["returncode"],
        "stderr_tail": res["stderr_tail"],
    }
    if res["status"] != "ok":
        out["error"] = res.get("error")
    out["log_path"] = _write_run_log(
        "reference_audit", pdir, prompt, res,
        {"status": res["status"], "findings_len": len(out["findings"])},
        envelope=out, paper_id=paper_id)
    return out


# --------------------------------------------------------------------------- #
# reference verifier (reference_verify) — the ONLINE half of the reference chain  #
# --------------------------------------------------------------------------- #

_VALID_VERDICTS = {"verified", "corrected", "rejected", "unverifiable", "retarget-internal"}
# The verifier emits one verdict object per flagged entry. Per the role prompt's
# §4 contract, that may be JSON **or** a labelled key/value block ("YAML-ish") —
# and real codex runs strongly prefer the latter, one ```yaml``` block per entry.
# So we accept both: JSON first (balanced ``{...}`` spans), then a dependency-free
# labelled-block parser (no PyYAML — it is not a dependency).
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
# a top-level (column-0) ``field: value`` line; the value may be empty (opens a
# nested mapping like ``confirmed_metadata:``) or a scalar.
_KV_TOP_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]?(.*)$")
# an indented ``field: value`` line — a member of the current nested mapping.
_KV_SUB_RE = re.compile(r"^[ \t]+([A-Za-z_][A-Za-z0-9_]*):[ \t]?(.*)$")
# fields whose empty value opens a nested mapping (indented sub-keys follow).
_KV_MAPPING_FIELDS = {"confirmed_metadata"}


def _norm_verdict(obj: Any) -> Optional[Dict[str, Any]]:
    """Keep ``obj`` only if it is a dict carrying a ``key`` (str) and a ``verdict``
    in ``_VALID_VERDICTS``; else ``None`` (malformed / non-verdict block)."""
    if not isinstance(obj, dict):
        return None
    key = obj.get("key")
    verdict = obj.get("verdict")
    if not isinstance(key, str) or verdict not in _VALID_VERDICTS:
        return None
    return obj


def _coerce_scalar(v: str) -> Any:
    """Strip one layer of surrounding quotes; map YAML nulls to ``None``."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    if v.lower() in ("null", "none", "~", ""):
        return None
    return v


def _parse_labelled_blocks(text: str) -> List[Dict[str, Any]]:
    """Parse the verifier's YAML-ish output (the shape a real codex emits): one
    block per entry, each a ``field: value`` list with column-0 top-level fields
    (``key``/``verdict``/``source_url``/``note``/``replacement_suggestion``) and an
    optional indented ``confirmed_metadata:`` sub-mapping (or ``null``). Code fences
    (```` ```yaml ````/```` ``` ````) are ignored. A new record begins at each
    top-level ``key:`` line. Dependency-free (no PyYAML)."""
    records: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    open_map: Optional[str] = None  # the top-level field currently taking sub-keys
    for raw in text.splitlines():
        if raw.lstrip().startswith("```"):
            open_map = None
            continue
        if not raw.strip():
            open_map = None
            continue
        top = _KV_TOP_RE.match(raw)
        if top and top.group(1) == "key":
            if cur is not None:
                records.append(cur)
            cur = {"key": _coerce_scalar(top.group(2))}
            open_map = None
            continue
        if cur is None:
            continue
        sub = _KV_SUB_RE.match(raw)
        if sub and open_map:
            mapping = cur.get(open_map)
            if not isinstance(mapping, dict):
                mapping = {}
                cur[open_map] = mapping
            val = _coerce_scalar(sub.group(2))
            if val is not None:
                mapping[sub.group(1)] = val
            continue
        if top:
            field, rawval = top.group(1), top.group(2)
            if rawval.strip() == "" and field in _KV_MAPPING_FIELDS:
                cur[field] = {}
                open_map = field
            else:
                cur[field] = _coerce_scalar(rawval)
                open_map = None
    if cur is not None:
        records.append(cur)
    return records


def _parse_verdicts(text: str) -> List[Dict[str, Any]]:
    """Parse the verifier's stdout into a list of well-formed verdict objects.

    Tolerant by design. **JSON first:** try the whole stdout as JSON (array or
    single object), then scan for individual balanced ``{...}`` spans embedded in
    prose. **Labelled blocks second:** if JSON yields nothing, parse the YAML-ish
    ``field: value`` blocks a real codex emits (``_parse_labelled_blocks``). Either
    way a block is kept only if it carries a ``key`` + a ``verdict`` in
    ``_VALID_VERDICTS``. Returns ``[]`` when nothing parses (an empty / junk run —
    the caller treats that as a non-promotion, so the ledger is not touched)."""
    out: List[Dict[str, Any]] = []
    stripped = text.strip()
    try:
        whole = json.loads(stripped)
        items = whole if isinstance(whole, list) else [whole]
        for it in items:
            n = _norm_verdict(it)
            if n is not None:
                out.append(n)
        if out:
            return out
    except (json.JSONDecodeError, ValueError):
        pass
    for m in _JSON_OBJ_RE.finditer(stripped):
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            continue
        n = _norm_verdict(obj)
        if n is not None:
            out.append(n)
    if out:
        return out
    # No JSON verdicts — fall back to the labelled-block (YAML-ish) form.
    for block in _parse_labelled_blocks(stripped):
        n = _norm_verdict(block)
        if n is not None:
            out.append(n)
    return out


_LEDGER_FIELD_RE = re.compile(r"^-\s+([A-Za-z_][\w-]*):\s*(.*)$")
_LEDGER_HEAD_RE = re.compile(r"^##\s+(.+?)\s*$")


def _parse_ledger_sections(text: str) -> Tuple[List[str], List[List[Any]]]:
    """Parse a REFERENCE_LEDGER into ``(preamble_lines, [[key, body]...])`` in order,
    where ``body`` is a list of ``(field, value)`` pairs (``('_raw', line)`` for
    anything that is not a ``- field: value`` line). Legacy ``## verifier delta …``
    append sections are dropped, so a delta-polluted ledger is
    compacted to the single-table form on the next write."""
    preamble: List[str] = []
    sections: List[List[Any]] = []
    cur: Optional[List[Any]] = None
    for ln in text.splitlines():
        # a '## key' heading (but not a '### ...' sub-heading)
        if ln.startswith("## ") and not ln.startswith("###"):
            cur = [_LEDGER_HEAD_RE.match(ln).group(1).strip(), []]
            sections.append(cur)
            continue
        if cur is None:
            preamble.append(ln)
        else:
            fm = _LEDGER_FIELD_RE.match(ln)
            cur[1].append((fm.group(1), fm.group(2)) if fm else ("_raw", ln))
    sections = [s for s in sections if not s[0].lower().startswith("verifier delta")]
    return preamble, sections


def _set_field(body: List[Any], field: str, value: str) -> None:
    """Update ``field`` in a section body in place if present, else append it."""
    for i, (f, _v) in enumerate(body):
        if f == field:
            body[i] = (field, value)
            return
    body.append((field, value))


def _apply_verdict_to_body(body: List[Any], v: Dict[str, Any]) -> None:
    """Rewrite one ledger row from a verdict. ``verified``/``corrected`` (which
    carry a ``source_url``) update the authoritative metadata + ``source_url`` and
    set ``verified-by: verifier``; every other verdict sets
    ``verified-by: unverified (<verdict>)`` and keeps the seeded metadata (the flag
    stays for the reviser). A ``note`` is recorded either way."""
    verdict = v.get("verdict")
    meta = v.get("confirmed_metadata") if isinstance(v.get("confirmed_metadata"), dict) else {}
    src = (v.get("source_url") or "").strip()
    note = (v.get("note") or "").strip()
    if verdict in ("verified", "corrected") and src:
        for f in ("authors", "title", "venue", "year", "doi"):
            if meta.get(f):
                _set_field(body, f, str(meta[f]))
        if meta.get("arxiv_id"):
            _set_field(body, "arxiv", str(meta["arxiv_id"]))
        _set_field(body, "source_url", src)
        _set_field(body, "verified-by", "verifier")
    else:
        _set_field(body, "verified-by", f"unverified ({verdict})")
    if note:
        _set_field(body, "note", note)


def _apply_ledger_verdicts(ledger_path: Path, verdicts: List[Dict[str, Any]]) -> None:
    """Apply the verifier's verdicts to ``REFERENCE_LEDGER.md`` **in place** — the
    ledger stays a single, always-current table (one ``## <key>`` row per
    reference), not an append-only log. For each verdict we rewrite the matching
    ``## <key>`` row's ``verified-by`` / ``source_url`` / metadata (creating the row
    if the key is new); no ``## verifier delta`` section is appended, so consumers
    (writer / auditor) never have to reconcile a body row against a later delta and
    the ledger cannot grow without bound. The ledger IS a work product the verifier
    may write (unlike ``main.tex``)."""
    text = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
    preamble, sections = _parse_ledger_sections(text)
    by_key = {key: body for key, body in sections}
    for v in verdicts:
        key = v.get("key")
        if not isinstance(key, str):
            continue
        if key in by_key:
            _apply_verdict_to_body(by_key[key], v)
        else:
            body: List[Any] = []
            _apply_verdict_to_body(body, v)
            sections.append([key, body])
            by_key[key] = body
    out: List[str] = []
    pre = "\n".join(preamble).rstrip("\n")
    if pre:
        out.append(pre)
    for key, body in sections:
        out.append("")
        out.append(f"## {key}")
        for f, val in body:
            if f == "_raw":
                if val.strip():
                    out.append(val)
            else:
                out.append(f"- {f}: {val}")
    ledger_path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")


def reference_verify(project: Optional[str] = None,
                 findings: Optional[str] = None,
                 paper_id: Optional[str] = None) -> Dict[str, Any]:
    """Verify the paper's flagged references ONLINE — the reference verifier, the
    middle of the ``auditor (offline) -> verifier (online) -> reviser`` chain
    (symmetric to ``worker -> verifier -> fact_graph``).

    Assembles the verifier prompt (``roles/AGENTS.md`` +
    ``roles/REFERENCE_VERIFIER_PROMPT.md`` + ``main.tex`` + ``REFERENCE_LEDGER.md``
    + the auditor's ``findings`` — and **no fact graph / style / structure**), then
    drives a codex over the **networked** path (``--dangerously-bypass-approvals-
    and-sandbox`` + the danus gateway at ``DANUS_ROLE=verifier`` exposing only
    ``search_arxiv_theorems`` + codex's built-in ``web_search``; empty cwd, so codex
    still cannot touch the project tree). It parses the per-entry verdict objects,
    and on an honest ``ok`` run updates ``REFERENCE_LEDGER.md`` **in place** — each
    verified/corrected row's ``verified-by`` becomes ``verifier`` (+ ``source_url``
    + authoritative metadata), other verdicts set ``verified-by: unverified
    (<verdict>)``. The ledger stays a single always-current table (one row per key),
    NOT an append-only delta log — so the writer/auditor never reconcile a stale
    body row against a later delta.

    Pass the auditor's ``findings`` (from ``reference_audit``) as the worklist; omitted
    → the verifier re-checks every ``unverified`` row / ``[cite/blocker]`` flag.

    It MAY write ``REFERENCE_LEDGER.md`` (a work product) but NEVER ``main.tex`` —
    rewriting ``\\cite``/``\\bibitem`` is the reviser's job; the returned verdicts
    include a one-line replacement suggestion per entry for the reviser.

    **Honesty:** the ledger is updated ONLY on an honest ``ok`` (zero exit,
    non-empty stdout). A nonzero exit / empty stdout / timeout → ``status != 'ok'``
    and the ledger is NOT touched (no false promotion). A degraded run whose
    verdicts are all ``unverifiable`` rewrites those rows as ``unverified
    (unverifiable)`` but promotes nothing.
    Returns ``{verdicts, ledger_path, status, returncode, stderr_tail, log_path}``."""
    pdir = resolve_project(project)
    ledger_path = assemble.paper_workspace(pdir, paper_id) / "REFERENCE_LEDGER.md"
    prompt = assemble.build_prompt("verifier", pdir, findings=findings, paper_id=paper_id)
    res = _drive_networked(prompt)
    out: Dict[str, Any] = {
        "verdicts": [],
        "ledger_path": str(ledger_path),
        "status": res["status"],
        "returncode": res["returncode"],
        "stderr_tail": res["stderr_tail"],
    }
    if res["status"] != "ok":
        # honesty gate: nonzero / empty / timeout -> do NOT update the ledger
        out["error"] = res.get("error")
        out["log_path"] = _write_run_log(
            "reference_verify", pdir, prompt, res,
            {"status": res["status"], "verdicts_count": 0, "applied_keys": []},
            envelope=out, paper_id=paper_id)
        return out
    verdicts = _parse_verdicts(res["stdout"])
    out["verdicts"] = verdicts
    if verdicts:
        _apply_ledger_verdicts(ledger_path, verdicts)
    applied_keys = [v["key"] for v in verdicts
                    if v.get("verdict") in ("verified", "corrected")
                    and (v.get("source_url") or "").strip()]
    out["log_path"] = _write_run_log(
        "reference_verify", pdir, prompt, res,
        {"status": res["status"], "verdicts_count": len(verdicts),
         "applied_keys": applied_keys},
        envelope=out, paper_id=paper_id)
    return out


def _closure_citation_map(pdir: Path, paper_id: Optional[str]) -> str:
    """A CITATION MAP for gap-fill: every PUBLISHED reference the target closure's
    facts already cite (from each fact's ``external_refs``), each with what it
    establishes (``cited_for``). This is the interface for "cite, don't re-prove":
    when the whole-doc verifier flags a standard/supporting result as unproved, the
    reviser CITES the matching published reference (the fact graph proved that step by
    citing this very paper) instead of adding an internal proof. Deduped by key; ``""``
    when the target is unset / there are no external refs."""
    from danus.core.factgraph import parse_frontmatter
    try:
        ids = assemble.closure_order(pdir, None, paper_id)
    except Exception:  # noqa: BLE001 — target unset etc.: no map (gap-fill still runs)
        return ""
    fg = FactGraph(pdir)
    refs: Dict[str, Dict[str, Any]] = {}
    for fid in ids:
        for r in parse_frontmatter(fg.get_raw(fid) or "")["external_refs"]:  # type: ignore[index]
            key = r.get("key")
            if not key:
                continue
            e = refs.setdefault(key, {"title": r.get("title", ""),
                                      "arxiv": r.get("arxiv", ""), "cited_for": []})
            cf = (r.get("cited_for") or "").strip()
            if cf and cf not in e["cited_for"]:
                e["cited_for"].append(cf)
    if not refs:
        return ""
    lines: List[str] = []
    for key in sorted(refs):
        e = refs[key]
        head = f"[{key}] {e['title']}".rstrip()
        if e["arxiv"]:
            head += f" (arXiv:{e['arxiv']})"
        lines.append(head)
        for cf in e["cited_for"][:4]:
            lines.append(f"    establishes: {cf}")
    return "\n".join(lines)


def paper_revise(project: Optional[str] = None, compile_log: Optional[str] = None,
                 notes: Optional[str] = None,
                 citation_fixes: Optional[str] = None,
                 verifier_feedback: Optional[str] = None,
                 add_facts: Optional[List[str]] = None,
                 paper_id: Optional[str] = None) -> Dict[str, Any]:
    """Revise an existing ``<project>/paper/main.tex`` (on a compile failure,
    cleared citation blockers, verifier citation fixes, operator editorial
    annotations, or a GAP-FILL round). The reviser gets
    ``main.tex`` + the REVISION_LOG tail + the trigger — NO fact graph except the
    specific verified facts a gap-fill round embeds. The reviser stays a
    stdout-only isolated codex; ALL compile / split / leak logic lives HERE.

    **Gap-fill mode (``verifier_feedback`` and/or ``add_facts``).** The whole-document
    ``paper_verify_math`` → revise INTERFACE: after the whole-doc verifier judges the
    paper not self-contained, the MAIN AGENT decides which facts close the gaps and
    calls this with three things carried together — ``verifier_feedback`` (the
    verifier's opinion / repair hints), ``notes`` (the main agent's own guidance), and
    ``add_facts`` (the fact ids to add; the tool embeds their VERIFIED
    statements+proofs so the reviser can prove the missing lemmas INTO the paper —
    inline or as new labelled results — making the development self-contained). This
    is the single seam from main agent → reviser for {verifier opinion, main-agent
    opinion, facts}. Returns ``gap_fill_facts`` (the ids embedded) in the envelope.

    **Change scope follows the trigger** (the reviser prompt branches on the
    assembled ``MODE:`` line): ``compile_log`` → fix only the compile errors;
    ``notes``/``citation_fixes`` → act only on those items;
    ``gap_fill`` → prove the main-agent-chosen facts into the paper;
    nothing → the global style-audit rewrite.

    **Reviser output contract.** stdout is two literal-separator sections —
    ``%%%MAIN_TEX%%%\\n<tex>\\n%%%REVISION_SUMMARY%%%\\n<summary>``. The tool splits
    them (``_split_reviser_output``) and writes the reviser's ACTUAL summary as the
    REVISION_LOG entry body; a missing ``%%%REVISION_SUMMARY%%%`` degrades honestly
    (tex still used, summary recorded as degraded).

    **Leak gate.** The split tex passes the SAME ``_LEAK_PATTERNS`` gate as
    ``paper_write``: on a hit the output is quarantined to ``main.leaky.tex``,
    ``main.tex`` is NOT overwritten, no REVISION_LOG entry is appended, and
    ``status='leak'``.

    **In-tool compile-retry loop.** After the leak gate, ``_compile_check``
    compiles the tex OUTSIDE the reviser (the compile is the tool's/orchestrator's
    gate, never the reviser's self-check). If it fails and attempts remain, the
    reviser is RE-driven with ``compile_log=<failing log tail>`` (carrying the same
    ``notes``/``citation_fixes``), up to
    ``DANUS_WRITE_PAPER_COMPILE_ATTEMPTS`` (env, default 3). Outcomes:
      - compile ok → write ``main.tex`` + REVISION_LOG, ``status='ok'``,
        ``compile='ok'``, ``compile_attempts=<n>``.
      - engine missing → do NOT loop; write once, ``status='ok'``,
        ``compile='skipped: no engine'``, ``compile_attempts=0`` (we cannot gate
        what we cannot run — honest).
      - attempts exhausted → do NOT overwrite ``main.tex``; quarantine the last
        attempt to ``main.uncompiled.tex``; ``status='compile_failed'`` with a
        compile-log tail.

    Returns ``{tex_path, status, returncode, revision_log_path, leak_findings,
    compile, compile_attempts, stderr_tail, log_path}``; on any non-``ok``
    codex status nothing is written (regression-safe)."""
    pdir = resolve_project(project)
    ws = assemble.paper_workspace(pdir, paper_id)
    tex_path = ws / "main.tex"
    log_path = ws / "REVISION_LOG.md"
    max_attempts = _compile_attempts()
    # the paper BEFORE this revision — the patch base. A legitimate revise never
    # collapses it; a drastic shrink is a degenerate patch and must NOT overwrite it.
    base_tex = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
    orig_tex_len = len(base_tex)

    # GAP-FILL assembly (the whole-document verify -> revise interface): the main
    # agent, after reading the whole-doc verifier's feedback,
    # chooses FACTS to add; this tool embeds those facts' verified statements+proofs
    # so the reviser can PROVE the missing lemmas into the paper. One trigger carrying
    # {verifier feedback, main-agent opinion (notes), facts}, together. Deterministic,
    # no codex, done before the drive loop.
    gap_fill_text: Optional[str] = None
    gap_fill_facts: List[str] = []
    if verifier_feedback or add_facts:
        pieces: List[str] = []
        if verifier_feedback and verifier_feedback.strip():
            pieces.append("VERIFIER FEEDBACK (why the whole-document verifier judged "
                          "the paper not self-contained / wrong — close these gaps):\n"
                          + verifier_feedback.strip())
        # CITE, don't re-prove: the closure's facts already cite published work for the
        # standard/deep steps — surface that map so the reviser cites it (exact key +
        # what it establishes) instead of adding internal proofs that descend the DAG.
        cmap = _closure_citation_map(pdir, paper_id)
        if cmap:
            pieces.append("PUBLISHED CITATIONS AVAILABLE (each is a real reference the "
                          "development's facts already cite, with what it establishes). "
                          "For a STANDARD / already-published supporting result the "
                          "verifier flagged, CITE the matching reference by its key (add "
                          "a \\bibitem if missing) with the precise theorem/def it gives "
                          "— do NOT re-prove it. Only genuinely NOVEL central results "
                          "need a full in-paper proof:\n" + cmap)
        if add_facts:
            gap_fill_facts = list(add_facts)
            pieces.append("FACTS TO ADD (the main agent selected these NOVEL results to "
                          "prove in full; their VERIFIED statements+proofs follow — prove "
                          "them into the paper, inline where natural or as new labelled "
                          "results, adapting to the paper's notation):\n"
                          + assemble.full_bodies_for(pdir, add_facts))
        gap_fill_text = "\n\n".join(pieces) or None

    out: Dict[str, Any] = {
        "tex_path": str(tex_path),
        "revision_log_path": str(log_path),
        "status": "error",
        "returncode": None,
        "leak_findings": [],
        "compile": "not run",
        "compile_attempts": 0,
        "stderr_tail": "",
    }
    if gap_fill_text is not None:
        out["gap_fill_facts"] = gap_fill_facts
    # mode/trigger for the run-log decisions (same rule as _append_revision_log).
    if gap_fill_text:
        _mode = "gap-fill+compile-fix" if compile_log else "gap-fill"
    elif compile_log:
        _mode = "compile-fix"
    elif notes or citation_fixes:
        _mode = "targeted-notes"
    else:
        _mode = "style-audit-pass"
    _trigger_bits = ([("compile_log")] if compile_log else []) + \
        (["citation_fixes"] if citation_fixes else []) + (["notes"] if notes else [])
    mode_trigger = f"{_mode} (trigger: {', '.join(_trigger_bits) or 'none'})"

    # ONE run log per paper_revise CALL (not per internal re-drive): the loop
    # tracks the LAST attempt's prompt/res + the per-attempt compile outcomes, and
    # the single winning return site writes the log with them.
    # The compile loop RE-drives the reviser with the failing log; `notes` and
    # `citation_fixes` are carried unchanged, `cur_compile_log` grows the trigger.
    cur_compile_log = compile_log
    last_tex: Optional[str] = None
    last_summary: Optional[str] = None
    last_log = ""
    attempts = 0
    prompt: Optional[str] = None
    res: Dict[str, Any] = {}
    compile_outcomes: List[str] = []

    for attempts in range(1, max_attempts + 1):
        if attempts == 1:
            # attempt 1: the SUBSTANTIVE revision (gap-fill / notes …).
            prompt = assemble.build_prompt("reviser", pdir, compile_log=cur_compile_log,
                                           notes=notes, citation_fixes=citation_fixes,
                                           gap_fill=gap_fill_text,
                                           paper_id=paper_id)
            res = _drive(prompt)
        else:
            # compile-retry: a LIGHTWEIGHT, LOW-EFFORT, targeted fix of the LAST
            # attempt's broken tex — fix ONLY the compile error, do not re-run the full
            # (high-effort) gap-fill or re-reason the paper. Mechanical.
            prompt = _compile_fix_prompt(last_tex or "", cur_compile_log or "")
            res = _drive(prompt, effort=_compile_fix_effort())
        out["status"] = res["status"]
        out["returncode"] = res["returncode"]
        out["stderr_tail"] = res["stderr_tail"]
        if res["status"] != "ok":
            # non-ok codex: nothing written (regression). Report honestly.
            out["error"] = res.get("error")
            out["compile"] = "not run"
            out["compile_attempts"] = 0
            out["log_path"] = _write_run_log(
                "paper_revise", pdir, prompt, res,
                {"mode/trigger": mode_trigger, "split": "n/a (non-ok codex)",
                 "leak_findings": [], "compile": "not run", "compile_attempts": 0,
                 "compile_outcomes": compile_outcomes}, envelope=out, paper_id=paper_id)
            return out

        # PATCH: the reviser emits find/replace edits; the tool applies them to the
        # paper (the base for attempt 1, the last attempt's tex on a compile-retry) —
        # so the reviser never re-emits the whole file (which it refuses / truncates on
        # a large paper). A round that applies ZERO edits produced nothing usable.
        patch_text, summary = _split_reviser_patch(_strip_code_fence(res["stdout"]))
        patch_base = base_tex if last_tex is None else last_tex
        tex, applied, patch_errors = _apply_reviser_patch(patch_base, patch_text)
        last_tex, last_summary = tex, summary
        split_state = (f"patch: {applied} edit(s) applied"
                       + (f", {len(patch_errors)} skipped" if patch_errors else ""))
        if applied == 0:
            out["status"] = "no_edits_applied"
            out["error"] = ("the reviser's patch applied no edits (no FIND matched the "
                            "paper, or no patch emitted); main.tex unchanged. "
                            + ("; ".join(patch_errors[:5]) if patch_errors else ""))
            out["patch_errors"] = patch_errors
            out["compile"] = "not run"
            out["compile_attempts"] = attempts - 1
            out["log_path"] = _write_run_log(
                "paper_revise", pdir, prompt, res,
                {"mode/trigger": mode_trigger, "split": split_state,
                 "patch_errors": patch_errors, "compile": "not run",
                 "compile_attempts": attempts - 1,
                 "compile_outcomes": compile_outcomes}, envelope=out, paper_id=paper_id)
            return out

        # DEGENERATE-SHRINK GUARD: a real revision never collapses the paper. If the
        # patched tex is a fraction of the original (a runaway delete), REJECT it —
        # never overwrite main.tex, quarantine, report honestly.
        if orig_tex_len > 2000 and len(tex) < 0.6 * orig_tex_len:
            shrunk_path = tex_path.with_name("main.shrunk.tex")
            shrunk_path.write_text(tex, encoding="utf-8")
            out["status"] = "degenerate_revision"
            out["error"] = (f"revision collapsed the paper from {orig_tex_len} to "
                            f"{len(tex)} chars — rejected; main.tex NOT overwritten "
                            f"(quarantined to {shrunk_path.name}). Re-run the round.")
            out["shrunk_tex_path"] = str(shrunk_path)
            out["compile"] = "not run"
            out["compile_attempts"] = attempts - 1
            out["log_path"] = _write_run_log(
                "paper_revise", pdir, prompt, res,
                {"mode/trigger": mode_trigger, "split": split_state,
                 "degenerate_shrink": f"{len(tex)} < 0.6*{orig_tex_len}",
                 "compile": "not run", "compile_attempts": attempts - 1,
                 "compile_outcomes": compile_outcomes}, envelope=out, paper_id=paper_id)
            return out

        leaks = leak_findings(tex, _LEAK_PATTERNS)
        out["leak_findings"] = leaks
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        if leaks:
            # Never overwrite a clean main.tex with a leaky revision; quarantine it
            # and report an honest non-ok status. No REVISION_LOG entry on a leaky
            # round. No compile attempt on leaked output.
            leaky_path = tex_path.with_name("main.leaky.tex")
            leaky_path.write_text(tex, encoding="utf-8")
            out["status"] = "leak"
            out["error"] = "revision contains leaked identifiers/machinery; main.tex not overwritten"
            out["leaky_tex_path"] = str(leaky_path)
            out["compile"] = "not run"
            out["compile_attempts"] = attempts - 1
            out["log_path"] = _write_run_log(
                "paper_revise", pdir, prompt, res,
                {"mode/trigger": mode_trigger, "split": split_state,
                 "leak_findings": leaks, "compile": "not run",
                 "compile_attempts": attempts - 1,
                 "compile_outcomes": compile_outcomes}, envelope=out, paper_id=paper_id)
            return out

        check = _compile_check(tex)
        last_log = check["log"]
        if not check["engine_available"]:
            # Cannot gate what we cannot run — write once, honest note, no loop.
            compile_outcomes.append("skipped: no engine")
            tex_path.write_text(tex, encoding="utf-8")
            _append_revision_log(log_path, compile_log=cur_compile_log, notes=notes,
                                 citation_fixes=citation_fixes,
                                 summary=summary, compile_status="skipped: no engine")
            out["status"] = "ok"
            out["compile"] = "skipped: no engine"
            out["compile_attempts"] = 0
            out["log_path"] = _write_run_log(
                "paper_revise", pdir, prompt, res,
                {"mode/trigger": mode_trigger, "split": split_state,
                 "leak_findings": [], "compile": "skipped: no engine",
                 "compile_attempts": 0, "compile_outcomes": compile_outcomes},
                envelope=out, paper_id=paper_id)
            return out
        if check["ok"]:
            compile_outcomes.append("ok")
            tex_path.write_text(tex, encoding="utf-8")
            _append_revision_log(log_path, compile_log=cur_compile_log, notes=notes,
                                 citation_fixes=citation_fixes,
                                 summary=summary, compile_status="ok")
            out["status"] = "ok"
            out["compile"] = "ok"
            out["compile_attempts"] = attempts
            out["log_path"] = _write_run_log(
                "paper_revise", pdir, prompt, res,
                {"mode/trigger": mode_trigger, "split": split_state,
                 "leak_findings": [], "compile": "ok", "compile_attempts": attempts,
                 "compile_outcomes": compile_outcomes}, envelope=out, paper_id=paper_id)
            return out
        # compile failed — RE-drive with the failing log tail (carry notes/fixes).
        compile_outcomes.append("failed")
        cur_compile_log = _log_tail(check["log"])

    # attempts exhausted — do NOT overwrite main.tex; quarantine the last attempt.
    if last_tex is not None:
        uncompiled = tex_path.with_name("main.uncompiled.tex")
        uncompiled.write_text(last_tex, encoding="utf-8")
        out["uncompiled_tex_path"] = str(uncompiled)
    out["status"] = "compile_failed"
    out["compile"] = "failed"
    out["compile_attempts"] = attempts
    out["compile_log_tail"] = _log_tail(last_log)
    out["error"] = (f"revision did not compile after {attempts} attempt(s); "
                    "main.tex not overwritten (quarantined to main.uncompiled.tex)")
    out["log_path"] = _write_run_log(
        "paper_revise", pdir, prompt, res,
        {"mode/trigger": mode_trigger,
         "split": "ok" if last_summary is not None else "degraded (no summary)",
         "leak_findings": [], "compile": "failed", "compile_attempts": attempts,
         "compile_outcomes": compile_outcomes,
         "compile_log_tail": _log_tail(last_log)}, envelope=out, paper_id=paper_id)
    return out


def _append_revision_log(log_path: Path, *, compile_log: Optional[str],
                         notes: Optional[str], citation_fixes: Optional[str] = None,
                         summary: Optional[str] = None,
                         compile_status: str = "ok") -> None:
    """Append one reviser round entry to REVISION_LOG.md. The entry BODY is the
    reviser's ACTUAL round summary (the ``%%%REVISION_SUMMARY%%%`` section the tool
    split out) — not a boilerplate stub. When ``summary`` is None (the reviser
    emitted no summary section) the body records the degradation honestly rather
    than fabricating one. A timestamp + trigger/mode + compile-status header is
    always written by the tool."""
    if compile_log:
        mode = "compile-fix"
    elif notes or citation_fixes:
        mode = "targeted-notes"
    else:
        mode = "style-audit-pass"
    trigger_bits = []
    if compile_log:
        trigger_bits.append("compile_log")
    if citation_fixes:
        trigger_bits.append("citation_fixes")
    if notes:
        trigger_bits.append("notes")
    trigger = ", ".join(trigger_bits) if trigger_bits else "none (style-audit pass)"
    body = summary if summary is not None else (
        "[degraded: reviser emitted no REVISION_SUMMARY section — the tex was still "
        "leak-checked, compiled, and written, but no round summary is available]"
    )
    entry = (
        f"\n## {utc_now()} — reviser (danus.write_paper)\n"
        f"- **mode:** {mode}  |  **trigger:** {trigger}  |  **compile:** {compile_status}\n\n"
        f"{body}\n"
    )
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        header = "# REVISION_LOG\n\n<!-- newest entries on top; tool entries appended -->\n"
        log_path.write_text(header + entry, encoding="utf-8")
    else:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)


# --------------------------------------------------------------------------- #
# paper_verify_math — whole-paper math verification gate                      #
# --------------------------------------------------------------------------- #

def _parse_paper_verdict(stdout: str) -> Tuple[Optional[str], str]:
    """Parse the THIRD verifier's (paper math verifier) output: the LAST JSON object
    that carries a ``verdict`` of ``correct``/``wrong`` (the prompt tells it to end
    with exactly that object). Returns ``(verdict, repair_hints)`` — ``verdict`` is
    the normalized lowercase string or ``None`` when none parses; ``repair_hints`` is
    the object's hints (empty on ``correct``, else hints or the report). Uses a
    balanced JSON scan (``raw_decode`` from each ``{``) so repair-hint text containing
    braces (LaTeX) does not break parsing."""
    dec = json.JSONDecoder()
    best: Optional[Dict[str, Any]] = None
    i = 0
    while True:
        j = stdout.find("{", i)
        if j == -1:
            break
        try:
            obj, end = dec.raw_decode(stdout, j)
        except json.JSONDecodeError:
            i = j + 1
            continue
        i = end
        if isinstance(obj, dict) and str(obj.get("verdict", "")).strip().lower() in ("correct", "wrong"):
            best = obj
    if best is None:
        return None, ""
    verdict = str(best.get("verdict")).strip().lower()
    hints = "" if verdict == "correct" else str(best.get("repair_hints") or best.get("report") or "")
    return verdict, hints


def paper_verify_math(project: Optional[str] = None,
                      paper_id: Optional[str] = None) -> Dict[str, Any]:
    """WHOLE-PAPER MATH VERIFICATION — verify the assembled paper AS WRITTEN,
    as ONE whole document, and gate deliver on a durable ledger.

    The facts were each verified individually before they were written. But the
    paper is a DIFFERENT artifact: the writer re-renders and re-stitches them
    (concision, "it suffices…", "WLOG…", dropped steps), and those seams are where
    a correct set of facts becomes an incorrect paper. So the paper must not be
    delivered until it passes verification **as written**.

    How it runs: one fresh paper-math verifier codex (a dedicated role, separate
    from the fact-submission verifier and the reference verifier) reads the whole
    ``main.tex`` development in order plus the confirmed REFERENCE_LEDGER, trusts
    the confirmed citations, and judges the paper's own reasoning +
    self-containedness. No fact graph, no slicing, no resident service — a
    one-shot codex run per call.

    Size: if the assembled prompt exceeds ``pmv.whole_doc_budget()``
    (``DANUS_PAPER_VERIFY_WHOLE_DOC_CAP``, default ~700K chars) the tool does NOT
    split — it records an honest ``too_large`` blocker. Decomposing the paper by
    results into self-contained parts — each culminating in a designated result —
    and driving them is the MAIN AGENT's job (the
    write-paper skill says how); hardcoded chunking is deliberately absent.

    Ledger: writes ONE ``whole-paper`` row to ``<paper>/VERIFY_LEDGER.md``
    (status ``correct`` / ``wrong`` / ``oversized`` / ``pending``); ONLY this tool
    writes verdict rows. Deliver is gated by ``pmv.deliver_ok`` reading the ledger
    (``correct`` / ``trusted`` / ``overridden`` pass).

    **Honesty:** a failed verify RUN (codex error / unparseable verdict) is
    ``status='verify_error'`` — NOT a paper that passed. ``status='passed'``
    requires an actual ``correct`` verdict.

    Returns ``{status, units_total, correct, wrong, verdict, repair_hints,
    body_chars, ledger_path, log_path, deliver_ok, blockers}``."""
    pdir = resolve_project(project)
    ws = assemble.paper_workspace(pdir, paper_id)
    ledger_path = ws / "VERIFY_LEDGER.md"
    tex_path = ws / "main.tex"

    if not tex_path.is_file():
        out = {
            "status": "no_paper",
            "error": f"no main.tex at {tex_path} — write the paper first",
            "units_total": 0, "correct": 0, "wrong": 0, "unresolved": 0,
            "oversized": 0, "uncovered": 0, "ledger_path": str(ledger_path),
            "deliver_ok": False,
            "blockers": ["no main.tex"],
        }
        out["log_path"] = _write_run_log(
            "paper_verify_math", pdir, None, None, {"no_paper": True},
            envelope=out, paper_id=paper_id)
        return out

    tex = tex_path.read_text(encoding="utf-8")
    prev = pmv.read_ledger(ledger_path)
    cap = pmv.whole_doc_budget()

    # WHOLE-DOCUMENT verification by the paper-math verifier (a dedicated codex
    # role, separate from the fact-submission verifier and the reference verifier):
    # it reads the whole paper in order, TRUSTS the ledger's confirmed precise
    # external citations, and scrutinizes the paper's own reasoning +
    # self-containedness. No fact graph, no slicing. A prompt over the single-call
    # budget is recorded 'too_large' (an explicit blocker) — decomposition by
    # results into self-contained parts is the main agent's job (see the skill),
    # never a hardcoded split here.
    body = pmv.document_body(tex)
    prompt = assemble.build_paper_math_verifier_prompt(pdir, paper_id=paper_id)
    if len(prompt) > cap:
        row = pmv.LedgerRow(
            unit_id="whole-paper", label="whole-paper", source_fact="",
            status="oversized", last_verdict="not-sent",
            repair_hints=(f"verifier prompt is {len(prompt)} chars (~{len(prompt)//4} "
                          f"tokens), over the single whole-doc budget {cap} — decompose "
                          "by results into self-contained parts, each culminating in a "
                          "designated result (see the write-paper skill), or raise "
                          "DANUS_PAPER_VERIFY_WHOLE_DOC_CAP"),
            attempts=pmv.merge_attempts(prev, "whole-paper"), last_checked_utc=pmv.utc())
        pmv.write_ledger(ledger_path, [row])
        ok, blockers = pmv.deliver_ok(ledger_path)
        out = {"status": "too_large", "units_total": 1, "correct": 0, "wrong": 0,
               "body_chars": len(body), "whole_doc_cap": cap,
               "ledger_path": str(ledger_path), "deliver_ok": ok, "blockers": blockers}
        out["log_path"] = _write_run_log(
            "paper_verify_math", pdir, prompt, None,
            {"whole_doc": True, "too_large": len(prompt), "cap": cap},
            envelope=out, paper_id=paper_id)
        return out

    verify_error: Optional[str] = None
    verdict: Optional[str] = None
    hints = ""
    res = _drive(prompt)
    if res["status"] != "ok":
        verify_error = res.get("error") or "paper-math verifier codex returned non-ok"
        hints = verify_error
    else:
        verdict, hints = _parse_paper_verdict(res["stdout"])
        if verdict is None:
            verify_error = "could not parse a verdict from the paper-math verifier output"
            hints = verify_error

    if verify_error is not None:
        status_row, last = "pending", "verify-error"
    else:
        status_row = "correct" if verdict == "correct" else "wrong"
        last = str(verdict)
    row = pmv.LedgerRow(
        unit_id="whole-paper", label="whole-paper", source_fact="",
        status=status_row, last_verdict=last, repair_hints=str(hints),
        attempts=pmv.merge_attempts(prev, "whole-paper"), last_checked_utc=pmv.utc())
    pmv.write_ledger(ledger_path, [row])

    ok, blockers = pmv.deliver_ok(ledger_path)
    if verify_error is not None:
        status = "verify_error"
    elif ok:
        status = "passed"
    else:
        status = "blocked"

    out = {
        "status": status,
        "units_total": 1,
        "correct": 1 if status_row == "correct" else 0,
        "wrong": 1 if status_row == "wrong" else 0,
        "verdict": verdict,
        "repair_hints": str(hints),
        "body_chars": len(body),
        "ledger_path": str(ledger_path),
        "deliver_ok": ok,
        "blockers": blockers,
    }
    if verify_error is not None:
        out["error"] = verify_error
    out["log_path"] = _write_run_log(
        "paper_verify_math", pdir, prompt, res,
        {"whole_doc": True, "verifier": "paper-math (third verifier)",
         "verdict": verdict, "status_row": status_row,
         "deliver_ok": ok, "body_chars": len(body), "repair_hints": str(hints)[:500]},
        envelope=out, paper_id=paper_id)
    return out


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #

_TOOLS = {
    "paper_subgraph": paper_subgraph,
    "paper_write": paper_write,
    "reference_audit": reference_audit,
    "reference_verify": reference_verify,
    "paper_revise": paper_revise,
    "paper_verify_math": paper_verify_math,
}


def build_app() -> FastMCP:
    """Build the stdio MCP app exposing the paper tools (paper_subgraph / paper_write
    / reference_audit / reference_verify / paper_revise / paper_verify_math).
    All are main-agent verbs; there is no role split here."""
    app = FastMCP("write-paper")
    for name, fn in _TOOLS.items():
        app.tool(name=name)(fn)
    return app
