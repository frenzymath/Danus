"""CHUNKED paper generation — write a paper whose full-proof closure exceeds
the model context window, section by section.

The single-pass ``paper_write`` drives ONE writer codex with the WHOLE target
closure's full proofs embedded. On a large proof (hundreds of facts) that prompt
overflows the model window, so the paper cannot be written at all. This module is
the fallback ``server.paper_write`` invokes only when the would-be single-pass
writer prompt is over budget (``DANUS_PAPER_WRITE_CHUNK_CHARS``). It is
**tool-layer chunking**, NOT an agentic retrieval writer: the planner and each
section writer stay NON-AGENTIC isolated codex (empty cwd, everything embedded,
output IS the text, no tool calls). We keep "only the needed facts per call" but
decide it in Python, sliced by section.

Three phases:

  1. PLAN (``assemble.build_planner_prompt`` — one codex call): the closure as
     STATEMENTS ONLY (small) -> the FIXED preamble + front matter, a section plan
     assigning EVERY closure fact to exactly one section (deterministic COVERAGE
     check), and the bibliography. The planner output is split on explicit
     separators (``%%%PREAMBLE%%% / %%%FRONTMATTER%%% / %%%SECTIONS%%% /
     %%%BIBLIOGRAPHY%%%``).
  2. FILL (``assemble.build_section_writer_prompt`` — one codex call per section):
     THIS section's facts in FULL (proofs) + every OTHER closure fact's STATEMENT
     ONLY (\\ref context) + the fixed preamble/front matter + the whole section
     plan. Output: this section's LaTeX + a ``%%%PROVENANCE%%%`` map.
  3. STITCH (deterministic Python, no codex): preamble + front matter + section
     bodies (plan order) + bibliography + ``\\end{document}``; the per-section
     provenance maps merged into one.

HONESTY: if the planner or ANY section writer returns non-ok, or coverage fails,
generation fails honestly — no ``main.tex`` is written and the failing phase is
reported. A partial paper is never emitted. The stitched whole is then handed back
to ``server.paper_write`` for the SAME downstream as single-pass (leak gate,
write, provenance split/write, run log, envelope) — this module does the assembly
+ codex driving + stitch, and returns a small result dict; the SIDE EFFECTS
(writing files, logging) stay in ``server`` so the single-pass and chunked paths
share one downstream.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import assemble

# Planner output separators (mirrors the reviser's literal-separator contract) —
# the tool splits deterministically on these, so the planner emits each on its own
# line. See PAPER_PLANNER_PROMPT.md §3.
_SEP_PREAMBLE = "%%%PREAMBLE%%%"
_SEP_FRONTMATTER = "%%%FRONTMATTER%%%"
_SEP_SECTIONS = "%%%SECTIONS%%%"
_SEP_BIBLIOGRAPHY = "%%%BIBLIOGRAPHY%%%"

# The section writer's provenance separator — same contract/marker as the
# single-pass writer (server._PROVENANCE_SEP), duplicated here to avoid an import
# cycle and to keep this module self-describing.
_SEP_PROVENANCE = "%%%PROVENANCE%%%"

# Default char budget for the single-pass writer prompt before we chunk. ~800000
# chars ≈ ~200K tokens, leaving output room under a ~272K window. Env-overridable
# (read at call time) so tests can force chunking on a small stub project.
_DEFAULT_CHUNK_CHARS = 800000

# A wrapping ```` ```lang ```` fence a model sometimes wraps output in — stripped
# per-section (and off the planner blocks) so it never corrupts the stitch. Mirrors
# server._strip_code_fence, duplicated here to avoid an import cycle.
_FENCE_OPEN_RE = re.compile(r"^```[A-Za-z0-9_+-]*[ \t]*\n")


def _strip_code_fence(s: str) -> str:
    """Remove a single OUTER wrapping markdown code fence if present; else return
    ``s`` unchanged. Real LaTeX never begins with ```` ``` ````."""
    t = s.strip("\n")
    m = _FENCE_OPEN_RE.match(t)
    if not m:
        return s
    t = t[m.end():]
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3].rstrip("\n")
    return t + "\n"


# --------------------------------------------------------------------------- #
# threshold                                                                    #
# --------------------------------------------------------------------------- #

def chunk_char_budget() -> int:
    """The char budget for the single-pass writer prompt: over it → chunk.
    ``DANUS_PAPER_WRITE_CHUNK_CHARS`` (env, read at call time) wins; a
    non-positive / unparseable value falls back to ``_DEFAULT_CHUNK_CHARS``."""
    raw = os.environ.get("DANUS_PAPER_WRITE_CHUNK_CHARS", "")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_CHUNK_CHARS
    return n if n > 0 else _DEFAULT_CHUNK_CHARS


def should_chunk(project_dir: Path, headline: Optional[List[str]],
                 paper_id: Optional[str],
                 fact_ids: Optional[List[str]] = None,
                 instructions: Optional[str] = None) -> Tuple[bool, int, int]:
    """Decide whether ``paper_write`` must chunk, by ESTIMATING the size of the
    would-be single-pass writer prompt (its char length) and comparing to the
    budget. Returns ``(over_budget, prompt_chars, budget)``.

    Back-compat is paramount: UNDER budget → the caller uses the EXISTING
    single-pass path completely unchanged (so existing tests + small papers are
    byte-for-byte identical). The estimate IS the real single-pass prompt
    (``build_writer_prompt`` — SELECTION-AWARE: it reflects ``fact_ids`` /
    ``instructions`` exactly), so there is no drift between the estimate and what
    would be sent. With a main-agent selection the estimate is the CURATED prompt, so
    chunking only fires when even the selected subset overflows (the extreme
    fallback)."""
    prompt = assemble.build_writer_prompt(
        Path(project_dir), headline=headline, paper_id=paper_id,
        fact_ids=fact_ids, instructions=instructions)
    budget = chunk_char_budget()
    n = len(prompt)
    return (n > budget, n, budget)


# --------------------------------------------------------------------------- #
# phase 1 — planner output parsing + coverage                                  #
# --------------------------------------------------------------------------- #

class ChunkError(RuntimeError):
    """A chunked-generation failure that must abort the paper honestly (no partial
    paper). Carries the ``phase`` that failed so the caller can report it."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


def _split_planner_output(stdout: str) -> Dict[str, str]:
    """Split the planner's stdout on its four separators into
    ``{preamble, frontmatter, sections, bibliography}`` (each the raw text between
    its separator and the next). Missing separators or out-of-order blocks raise a
    ``ChunkError('plan', ...)`` — no partial paper. The separators must appear in
    the canonical order (preamble -> frontmatter -> sections -> bibliography)."""
    order = [
        ("preamble", _SEP_PREAMBLE),
        ("frontmatter", _SEP_FRONTMATTER),
        ("sections", _SEP_SECTIONS),
        ("bibliography", _SEP_BIBLIOGRAPHY),
    ]
    idxs: List[Tuple[str, str, int]] = []
    for name, sep in order:
        i = stdout.find(sep)
        if i == -1:
            raise ChunkError("plan", f"planner output missing separator {sep}")
        idxs.append((name, sep, i))
    # enforce canonical order
    positions = [i for _n, _s, i in idxs]
    if positions != sorted(positions):
        raise ChunkError("plan", "planner separators are out of order "
                                 "(expected preamble, frontmatter, sections, bibliography)")
    out: Dict[str, str] = {}
    for k, (name, sep, i) in enumerate(idxs):
        start = i + len(sep)
        end = idxs[k + 1][2] if k + 1 < len(idxs) else len(stdout)
        body = stdout[start:end]
        # drop the rest of the separator's own line (up to its newline)
        nl = body.find("\n")
        out[name] = body[nl + 1:] if nl != -1 else ""
    return out


def _parse_sections(sections_block: str) -> List[Dict[str, Any]]:
    """Parse the ``%%%SECTIONS%%%`` JSON array into a list of
    ``{title, label, fact_ids}`` dicts. Tolerant of a surrounding ```json code
    fence. A malformed array / wrong shape raises ``ChunkError('plan', ...)``."""
    text = sections_block.strip()
    # strip an optional ```json ... ``` fence
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ChunkError("plan", f"SECTIONS block is not valid JSON: {e}")
    if not isinstance(data, list) or not data:
        raise ChunkError("plan", "SECTIONS block must be a non-empty JSON array")
    out: List[Dict[str, Any]] = []
    seen_labels: set = set()
    for i, sec in enumerate(data):
        if not isinstance(sec, dict):
            raise ChunkError("plan", f"SECTIONS[{i}] is not an object")
        title = sec.get("title")
        label = sec.get("label")
        fact_ids = sec.get("fact_ids", [])
        if not isinstance(title, str) or not title.strip():
            raise ChunkError("plan", f"SECTIONS[{i}] has no valid 'title'")
        if not isinstance(label, str) or not label.strip():
            raise ChunkError("plan", f"SECTIONS[{i}] has no valid 'label'")
        if label in seen_labels:
            raise ChunkError("plan", f"duplicate section label {label!r}")
        seen_labels.add(label)
        if not isinstance(fact_ids, list) or not all(isinstance(f, str) for f in fact_ids):
            raise ChunkError("plan", f"SECTIONS[{i}] 'fact_ids' must be a list of strings")
        out.append({"title": title, "label": label, "fact_ids": list(fact_ids)})
    return out


def normalize_coverage(sections: List[Dict[str, Any]],
                       closure_ids: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Deterministically REPAIR a planner's section assignment so every closure fact
    is covered EXACTLY once — tolerating a slightly-imperfect planner instead of
    aborting the whole write (real planners duplicate a few facts, drop a few, or emit
    a stray id). Rules:
      * a fact assigned to several sections is kept in its FIRST section only (deduped);
      * an assigned id NOT in the closure is dropped;
      * closure facts left unassigned are swept into a final ``Additional results``
        section — so the paper still PRESENTS every used fact (self-containedness).
    Returns ``(repaired_sections, repair_log)``; ``repair_log`` names what was fixed."""
    closure_set = set(closure_ids)
    seen: set = set()
    repaired: List[Dict[str, Any]] = []
    dup = extra = 0
    for sec in sections:
        kept: List[str] = []
        for f in sec["fact_ids"]:
            if f not in closure_set:
                extra += 1
                continue
            if f in seen:
                dup += 1
                continue
            seen.add(f)
            kept.append(f)
        repaired.append({**sec, "fact_ids": kept})
    missing = [f for f in closure_ids if f not in seen]
    log: List[str] = []
    if dup:
        log.append(f"deduped {dup} fact(s) assigned to >1 section (kept first)")
    if extra:
        log.append(f"dropped {extra} assigned id(s) not in the closure")
    if missing:
        used_labels = {s["label"] for s in repaired}
        lbl = "sec:additional"
        i = 1
        while lbl in used_labels:
            i += 1
            lbl = f"sec:additional-{i}"
        repaired.append({"title": "Additional results", "label": lbl, "fact_ids": missing})
        log.append(f"swept {len(missing)} unassigned closure fact(s) into '{lbl}'")
    return repaired, log


def check_coverage(sections: List[Dict[str, Any]], closure_ids: List[str]) -> None:
    """Deterministic, HONEST coverage check: every closure fact id must appear in
    EXACTLY one section's ``fact_ids`` — no fact unassigned, none duplicated, and no
    assigned id outside the closure. Any violation raises ``ChunkError('plan',
    ...)`` so the caller aborts without emitting a partial paper."""
    closure_set = set(closure_ids)
    assigned: List[str] = []
    for sec in sections:
        assigned.extend(sec["fact_ids"])
    assigned_set = set(assigned)

    # duplicates (a fact assigned to two sections, or twice in one)
    if len(assigned) != len(assigned_set):
        seen: set = set()
        dups = sorted({f for f in assigned if f in seen or seen.add(f)})
        raise ChunkError("plan", f"facts assigned to more than one section: {dups}")
    # ids assigned that are not in the closure
    extra = sorted(assigned_set - closure_set)
    if extra:
        raise ChunkError("plan", f"section plan assigns ids not in the closure: {extra}")
    # closure facts left unassigned
    missing = [f for f in closure_ids if f not in assigned_set]
    if missing:
        raise ChunkError("plan", f"closure facts unassigned to any section: {missing}")


# --------------------------------------------------------------------------- #
# phase 2 — section fill output split                                          #
# --------------------------------------------------------------------------- #

def _split_section_output(stdout: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Split ONE section writer's stdout into ``(section_tex, provenance_or_None)``
    on ``%%%PROVENANCE%%%`` (same contract as the single-pass writer). Everything
    before the marker is the section body (what the leak gate + stitch see); after
    it is a JSON ``{label: fact_id}`` map. No marker / malformed JSON / non-dict →
    ``(stdout, None)`` (a plain-tex section is unchanged)."""
    if _SEP_PROVENANCE not in stdout:
        return _strip_code_fence(stdout), None
    tex_part, prov_part = stdout.split(_SEP_PROVENANCE, 1)
    try:
        data = json.loads(prov_part.strip())
    except (json.JSONDecodeError, ValueError):
        return _strip_code_fence(tex_part), None
    return _strip_code_fence(tex_part), (data if isinstance(data, dict) else None)


# --------------------------------------------------------------------------- #
# phase 3 — stitch                                                             #
# --------------------------------------------------------------------------- #

def stitch(preamble: str, frontmatter: str, section_bodies: List[str],
           bibliography: str) -> str:
    """Deterministically assemble main.tex = preamble + front matter + section
    bodies (in plan order) + bibliography + ``\\end{document}``. Whitespace between
    blocks is normalized to a single blank line; the planner's front matter is
    expected to contain ``\\begin{document}`` and ``\\maketitle`` (per its role
    prompt), and no block is expected to carry ``\\end{document}`` (this adds the
    one canonical closer). If a block already ends the document, the extra closer is
    still appended verbatim — the compile gate (downstream) catches a malformed
    document; this function does not silently repair, it stitches honestly."""
    parts: List[str] = [preamble.rstrip("\n"), frontmatter.rstrip("\n")]
    for body in section_bodies:
        parts.append(body.rstrip("\n"))
    parts.append(bibliography.rstrip("\n"))
    stitched = "\n\n".join(p for p in parts if p.strip())
    if "\\end{document}" not in stitched:
        stitched = stitched + "\n\n\\end{document}\n"
    else:
        stitched = stitched + "\n"
    return stitched


# --------------------------------------------------------------------------- #
# orchestration                                                                #
# --------------------------------------------------------------------------- #

def generate(
    project_dir: Path,
    *,
    headline: List[str],
    paper_id: Optional[str],
    drive: Callable[[str], Dict[str, Any]],
    fact_ids: Optional[List[str]] = None,
    instructions: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the three-phase chunked generation and return a small result dict the
    caller (``server.paper_write``) turns into the paper + envelope.

    ``drive`` is the codex driver (``server._drive``) — injected so this module is
    codex/network-free and offline-testable. ``fact_ids`` (the main agent's
    SELECTION) + ``instructions`` (its editorial direction) mirror the single-pass
    writer: when a selection is given the coverage set is EXACTLY that curated
    subset (partitioned across sections), and the selection's direct-predecessor
    statements are added to every section's ``\\ref`` context; when omitted the
    whole target closure is partitioned (legacy behavior, unchanged). On SUCCESS
    returns::

        {"ok": True, "tex": <stitched main.tex>, "provenance": <merged map>,
         "sections": <n>, "phase_logs": [<per-phase dicts>], "plan_res": ...,
         "section_res": [...]}

    where ``tex`` still goes through the caller's leak gate + write. On FAILURE
    (planner/section non-ok, coverage/parse failure) returns::

        {"ok": False, "phase": <"plan"|"section:<label>">, "error": <msg>,
         "phase_logs": [...], "res": <the failing codex res or None>, "prompt": ...}

    No ``main.tex`` is written here (or by the caller on a failure) — a partial
    paper is never emitted."""
    project_dir = Path(project_dir)
    phase_logs: List[Dict[str, Any]] = []

    # ---- phase 1: PLAN (statements only) --------------------------------- #
    plan_prompt = assemble.build_planner_prompt(
        project_dir, headline=headline, paper_id=paper_id,
        fact_ids=fact_ids, instructions=instructions)
    plan_res = drive(plan_prompt)
    phase_logs.append({"phase": "plan", "status": plan_res.get("status"),
                       "returncode": plan_res.get("returncode")})
    if plan_res.get("status") != "ok":
        return {"ok": False, "phase": "plan",
                "error": plan_res.get("error") or "planner codex returned non-ok",
                "phase_logs": phase_logs, "res": plan_res, "prompt": plan_prompt}

    try:
        blocks = _split_planner_output(plan_res["stdout"])
        sections = _parse_sections(blocks["sections"])
        # The COVERAGE set (each fact assigned to exactly one section) is the main
        # agent's SELECTION when given, else the whole closure. Referenced-only facts
        # (direct predecessors of the selection) are NEVER assigned to a section —
        # they are \ref context, embedded as statements in every section.
        if fact_ids:
            coverage_ids, referenced_ids = assemble.selected_partition(project_dir, fact_ids)
        else:
            coverage_ids = assemble.closure_order(project_dir, headline, paper_id)
            referenced_ids = []
        # REPAIR the plan (dedupe / drop-stray / sweep-unassigned) rather than abort:
        # a real planner duplicates or drops a few facts; normalize so every fact is
        # covered exactly once and the paper still presents them all (self-contained).
        sections, cov_log = normalize_coverage(sections, coverage_ids)
        phase_logs.append({"phase": "coverage", "repairs": cov_log})
    except ChunkError as e:
        return {"ok": False, "phase": e.phase, "error": str(e),
                "phase_logs": phase_logs, "res": plan_res, "prompt": plan_prompt}

    preamble = blocks["preamble"]
    frontmatter = blocks["frontmatter"]
    bibliography = blocks["bibliography"]
    # the fixed preamble+frontmatter handed to every section writer (macro/label
    # consistency) and a compact section-plan digest (titles+labels, in order).
    preamble_frontmatter = preamble.rstrip("\n") + "\n\n" + frontmatter.rstrip("\n") + "\n"
    section_plan_digest = "\n".join(
        f"{i+1}. \\section{{{s['title']}}}  ->  \\label{{{s['label']}}}"
        for i, s in enumerate(sections))

    # ---- phase 2: per-section FILL --------------------------------------- #
    section_bodies: List[str] = []
    merged_provenance: Dict[str, Any] = {}
    section_res_log: List[Dict[str, Any]] = []
    for sec in sections:
        this_ids = sec["fact_ids"]
        # OTHER statements = only the \ref context THIS section actually needs — the
        # direct predecessors of this section's facts (bounded, local). Embedding the
        # whole closure's statements in every section overflowed codex's input
        # hard-limit on a deep closure (~470 facts → 1.4M > 1,048,576 chars).
        other_ids = assemble.section_ref_context_ids(
            project_dir, this_ids, coverage_ids + referenced_ids)
        sec_prompt = assemble.build_section_writer_prompt(
            project_dir,
            section_title=sec["title"],
            section_label=sec["label"],
            section_facts=assemble.full_bodies_for(project_dir, this_ids),
            other_statements=assemble.statements_for(project_dir, other_ids),
            preamble_frontmatter=preamble_frontmatter,
            section_plan=section_plan_digest,
            paper_id=paper_id,
        )
        sec_res = drive(sec_prompt)
        section_res_log.append({"label": sec["label"], "status": sec_res.get("status"),
                                "returncode": sec_res.get("returncode")})
        phase_logs.append({"phase": f"section:{sec['label']}",
                           "status": sec_res.get("status"),
                           "returncode": sec_res.get("returncode")})
        if sec_res.get("status") != "ok":
            return {"ok": False, "phase": f"section:{sec['label']}",
                    "error": sec_res.get("error") or "section-writer codex returned non-ok",
                    "phase_logs": phase_logs, "res": sec_res, "prompt": sec_prompt,
                    "section_res": section_res_log}
        body, prov = _split_section_output(sec_res["stdout"])
        section_bodies.append(body)
        if isinstance(prov, dict):
            # merge; a later section never silently overwrites an earlier label —
            # labels are unique across sections by construction (each fact lives in
            # one section), so a collision would be a section-writer bug: keep first
            # and record nothing extra (the map is optional enrichment).
            for k, v in prov.items():
                merged_provenance.setdefault(k, v)

    # ---- phase 3: STITCH (deterministic) --------------------------------- #
    tex = stitch(preamble, frontmatter, section_bodies, bibliography)
    phase_logs.append({"phase": "stitch", "status": "ok", "sections": len(sections)})
    return {"ok": True, "tex": tex, "provenance": merged_provenance or None,
            "sections": len(sections), "phase_logs": phase_logs,
            "plan_res": plan_res, "section_res": section_res_log}
