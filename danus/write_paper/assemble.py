"""Deterministic per-role prompt assembler for the write-paper roles.

Pure functions: given a role and a project dir, read the fixed skill files
(role prompts / style / boilerplate) and the project's paper data + fact-graph
content, and concatenate them into a single prompt string with explicit section
delimiters. No codex, no network, no writes — everything here is testable in
isolation.

Two problems this solves:

1. The large bytes (style guide + fact-graph content) are assembled *here*, so
   they never enter the main agent's context; the main agent passes only
   ``{project, headline, ...}``.
2. Each role gets a **minimal, non-overlapping** input set (the per-role table below
   is the isolation contract, enforced by ``tests/test_assemble.py``):
     - writer   embeds the target-closure facts + style + structure (+ optional exemplar);
     - auditor  gets ONLY ``main.tex`` + ledger (NO facts, NO style/structure);
     - verifier gets ONLY ``main.tex`` (bibliography) + ledger + the auditor's
                findings (NO facts, NO style/structure) — the ONLINE half of the
                auditor→verifier→reviser chain;
     - reviser  gets NO fact graph.
   Every role's prompt embeds ``roles/AGENTS.md`` verbatim (the PRIME DIRECTIVE).

The fixed files live in the skill dir (operator-editable), located at call time
via ``DANUS_WRITE_PAPER_SKILL_DIR`` (default ``<repo_root>/agents/skills/write-paper``);
never read at import time. Every fixed file is read verbatim, in full — no
summarizing, no truncation. Fact reading uses ``danus.core.FactGraph`` (never
re-mining citations from prose).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from danus.authoring.common import (
    PROJECT_NAME_RE,
    body_sections,
    read_fixed,
    read_project,
    section,
)
from danus.core import FactGraph
from danus.core.factgraph import parse_frontmatter, statement_of

# The package lives at <repo_root>/danus/write_paper/assemble.py, so the repo root is
# two parents up; the default skill dir is the shipped write-paper skill.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SKILL_DIR = _REPO_ROOT / "agents" / "skills" / "write-paper"

ROLES = ("writer", "auditor", "reviser", "verifier")

# The project-level home for the finalized target theorem(s), written by
# ``danus finalize`` — a sibling of PROBLEM.md / fact_graph/ / paper/.
TARGET_FILE = "TARGET.md"

# The recorded-target sources ``resolve_headline`` can report (see its docstring).
HEADLINE_SOURCES = ("arg", "brief", "target", "unset")

# The canonical DEFAULT paper slug. A paper_id that is None / "" / this slug maps
# to the LEGACY paths (workspace ``<project>/paper/`` + target ``<project>/TARGET.md``)
# so existing single-paper projects are byte-for-byte unchanged. Only a *non-default*
# paper_id opens the multi-paper layout under ``<project>/papers/<paper_id>/``.
DEFAULT_PAPER_ID = "main"


# --------------------------------------------------------------------------- #
# per-paper workspace resolution (Item B — multiple papers per project)        #
# --------------------------------------------------------------------------- #

def _is_default_paper(paper_id: Optional[str]) -> bool:
    """A paper_id is the DEFAULT (legacy) paper when it is None, blank, or the
    canonical ``DEFAULT_PAPER_ID`` slug. The default paper keeps the legacy paths."""
    return not paper_id or paper_id == DEFAULT_PAPER_ID


def _validate_paper_id(paper_id: str) -> str:
    """Validate a non-default paper_id as a SINGLE safe path segment (reusing the
    ``PROJECT_NAME_RE`` shape) so it can never escape the project dir. Returns it
    unchanged on success; raises ``ValueError`` otherwise."""
    if not PROJECT_NAME_RE.match(paper_id):
        raise ValueError(
            f"invalid paper_id: {paper_id!r} (must be a single safe path segment "
            f"matching {PROJECT_NAME_RE.pattern})"
        )
    return paper_id


def paper_workspace(project_dir: Path, paper_id: Optional[str] = None) -> Path:
    """The per-paper workspace dir — the SINGLE seam every paper file path goes
    through (main.tex / REFERENCE_LEDGER.md / REVISION_LOG.md / VERIFY_LEDGER.md /
    PROJECT_BRIEF.md / .provenance.json / .runs/).

    Default (paper_id None / "" / ``DEFAULT_PAPER_ID``) → ``<project>/paper/``
    (LEGACY — existing single-paper projects unchanged). Otherwise →
    ``<project>/papers/<paper_id>/`` (paper_id validated to a single safe segment).

    This ONLY changes WHERE files live; the closure math is untouched (the writer's
    facts are still the transitive-predecessor closure of the resolved headline)."""
    project_dir = Path(project_dir)
    if _is_default_paper(paper_id):
        return project_dir / "paper"
    return project_dir / "papers" / _validate_paper_id(paper_id)  # type: ignore[arg-type]


def paper_target_path(project_dir: Path, paper_id: Optional[str] = None) -> Path:
    """The per-paper TARGET.md path (the finalized target fact ids ``danus finalize``
    records; ``resolve_headline`` reads).

    Default → ``<project>/TARGET.md`` (LEGACY project-root, unchanged). Otherwise →
    ``<project>/papers/<paper_id>/TARGET.md`` (inside the paper's own workspace)."""
    project_dir = Path(project_dir)
    if _is_default_paper(paper_id):
        return project_dir / TARGET_FILE
    return paper_workspace(project_dir, paper_id) / TARGET_FILE


class TargetUnsetError(RuntimeError):
    """Raised when the paper's target is UNSET — no explicit headline arg, no
    brief ``headline_fact_ids``, and no recorded ``<project>/TARGET.md``. The
    write-paper pipeline REFUSES to guess a target from the graph shape; the
    operator must run ``danus finalize <project> <fact_id>`` (or fill the brief's
    ``headline_fact_ids``) first. ``server.paper_write`` turns this into a
    ``needs_target`` result rather than silently embedding all facts."""


# --------------------------------------------------------------------------- #
# config resolution (env read at CALL time — testable / reconfigurable)       #
# --------------------------------------------------------------------------- #

def skill_dir() -> Path:
    """The operator-editable skill dir holding the fixed role/style/boilerplate
    files. ``DANUS_WRITE_PAPER_SKILL_DIR`` (env) wins; default is the shipped skill."""
    override = os.environ.get("DANUS_WRITE_PAPER_SKILL_DIR", "")
    return Path(override) if override else _DEFAULT_SKILL_DIR


# --------------------------------------------------------------------------- #
# section helpers                                                             #
# --------------------------------------------------------------------------- #

def _read_fixed(rel: str) -> str:
    """Read a fixed skill file **verbatim, in full** from the write-paper skill dir
    (thin wrapper over ``authoring.common.read_fixed`` binding ``skill_dir()``)."""
    return read_fixed(skill_dir(), rel)


def _read_project(project_dir: Path, rel: str) -> str:
    """Read a required per-project paper file verbatim; fail loudly if missing."""
    return read_project(project_dir, rel)


# --------------------------------------------------------------------------- #
# brief structured fields (headline_fact_ids / structural_exemplar)           #
# --------------------------------------------------------------------------- #

# A structured field lives on its own line as ``field: value`` inside the brief
# markdown. ``headline_fact_ids`` is a comma/space-separated list of fact ids (or
# blank); ``structural_exemplar`` is one anchor folder name (or blank). These are
# the machine-read fields; the surrounding prose is for humans.
_HEADLINE_FIELD_RE = re.compile(r"^\s*headline_fact_ids\s*:\s*(.*?)\s*$", re.IGNORECASE)
_EXEMPLAR_FIELD_RE = re.compile(r"^\s*structural_exemplar\s*:\s*(.*?)\s*$", re.IGNORECASE)
# A fact id token: the fact_ slug shape used across the graph. Keeps stray words /
# markdown out of the list even if the operator wrote prose on the same line.
_FACT_ID_RE = re.compile(r"fact_[A-Za-z0-9_]+")
# TARGET.md ids can be either a readable ``fact_`` slug OR a bare content-addressed
# hex id (what ``FactGraph.add`` returns, e.g. ``1a131721f439cade``). The reader is
# forgiving because ``danus finalize`` already validated the ids against the graph
# before writing; this just drops prose/labels.
_TARGET_ID_RE = re.compile(r"fact_[A-Za-z0-9_]+|\b[0-9a-f]{8,}\b")


def _read_brief(project_dir: Path, paper_id: Optional[str] = None) -> str:
    """The paper's PROJECT_BRIEF.md text, or ``""`` if absent. Rooted at the
    per-paper workspace (default → ``<project>/paper/``)."""
    path = paper_workspace(project_dir, paper_id) / "PROJECT_BRIEF.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def brief_headline_fact_ids(project_dir: Path, paper_id: Optional[str] = None) -> List[str]:
    """Parse the brief's ``headline_fact_ids`` field into a list of fact ids.

    Returns ``[]`` when the field is absent, blank, or holds only a placeholder
    (angle-bracket template text like ``<...>``). Accepts BOTH a readable ``fact_``
    slug AND a bare content-addressed hex id (``FactGraph.add`` returns 16-hex, e.g.
    ``f469b7af3103b419``) — the same shapes ``TARGET.md`` accepts, so the brief path
    is not silently ``unset`` on a hex-id deployment. Template prose on the line is
    ignored; ``paper_write`` validates the ids against the graph before use."""
    for line in _read_brief(project_dir, paper_id).splitlines():
        m = _HEADLINE_FIELD_RE.match(line)
        if m:
            return _TARGET_ID_RE.findall(m.group(1))
    return []


def brief_structural_exemplar(project_dir: Path, paper_id: Optional[str] = None) -> Optional[str]:
    """Parse the brief's ``structural_exemplar`` field: the anchor folder name to
    imitate for STRUCTURE, or None when blank / absent / a template placeholder."""
    for line in _read_brief(project_dir, paper_id).splitlines():
        m = _EXEMPLAR_FIELD_RE.match(line)
        if m:
            val = m.group(1).strip()
            # blank, or an un-filled ``<placeholder>`` from the template → none
            if not val or val.startswith("<"):
                return None
            return val
    return None


def target_fact_ids(project_dir: Path, paper_id: Optional[str] = None) -> List[str]:
    """The finalized target fact ids recorded in the paper's TARGET.md (written by
    ``danus finalize``), or ``[]`` when the file is absent / blank. The path is
    resolved via ``paper_target_path`` (default → legacy ``<project>/TARGET.md``).

    Format (trivially parseable, human-readable): one fact id per line. A leading
    ``target_fact_ids:`` label line is accepted and its inline ids are parsed too;
    ``#`` comment lines and blank lines are ignored. Only ``fact_`` tokens are
    kept, so any surrounding prose is dropped. The file is validated at write time
    (``danus finalize`` refuses ids the fact graph does not have), so this reader
    stays a pure, forgiving parse."""
    path = paper_target_path(Path(project_dir), paper_id)
    if not path.is_file():
        return []
    ids: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # drop a leading ``target_fact_ids:`` / ``target:`` label so its own
        # ``fact_ids`` token is not mistaken for a fact id.
        stripped = re.sub(r"^\s*target(_fact_ids)?\s*:\s*", "", stripped, flags=re.IGNORECASE)
        for tok in _TARGET_ID_RE.findall(stripped):
            if tok not in ids:
                ids.append(tok)
    return ids


def write_target_fact_ids(project_dir: Path, fact_ids: List[str],
                          paper_id: Optional[str] = None) -> Path:
    """Write the finalized target fact ids to the paper's TARGET.md (one id per
    line, with a short header), resolved via ``paper_target_path`` (default →
    legacy ``<project>/TARGET.md``; else ``<project>/papers/<paper_id>/TARGET.md``,
    whose parent dir is created). Returns the path. Callers (``danus finalize``)
    validate the ids against the fact graph BEFORE calling this — nothing here
    checks existence."""
    path = paper_target_path(Path(project_dir), paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# TARGET — the finalized target theorem(s) for this project",
        "#",
        "# Written by `danus finalize <project> <fact_id> ...`; read by write-paper",
        "# (assemble.resolve_headline). One fact id per line.",
        "",
    ]
    body.extend(fact_ids)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def _terminal_facts(fg: FactGraph) -> List[str]:
    """The deepest TERMINAL facts: those that are no other fact's predecessor.

    In a verified proof DAG these are candidate target results (nothing is built
    on top of them). Deterministic (sorted-id order from ``fg.list()``).

    NB: this is ONLY the ``danus finalize`` SUGGESTION helper now — it lists
    candidates for the operator to choose from. It is deliberately **not** a
    ``resolve_headline`` fallback: write-paper refuses to guess a target (see
    ``resolve_headline`` / ``TargetUnsetError``)."""
    all_ids = fg.list()
    is_predecessor: set = set()
    for fid in all_ids:
        for p in fg.predecessors(fid):
            is_predecessor.add(p)
    return [fid for fid in all_ids if fid not in is_predecessor]


def resolve_headline(
    project_dir: Path, headline: Optional[List[str]] = None,
    paper_id: Optional[str] = None,
) -> Tuple[List[str], str]:
    """Resolve the paper's headline (target) fact ids, returning ``(ids, source)``.

    Precedence — the target must be RECORDED; there is NO silent guess:
      (a) an explicit ``headline`` arg (the caller knows the targets) → ``"arg"``;
      (b) else the brief's ``headline_fact_ids`` field, when non-empty → ``"brief"``;
      (c) else the finalized target in the paper's TARGET.md (written by
          ``danus finalize``; default → ``<project>/TARGET.md``) → ``"target"``;
      (d) else UNSET → ``("", "unset")`` with ``ids == []``.

    ``paper_id`` roots the brief + TARGET.md at the per-paper workspace (default →
    the legacy project paths). The closure algorithm is UNCHANGED — only where the
    headline set is read from changes.

    ``source`` is one of ``HEADLINE_SOURCES``. On ``"unset"`` the caller must NOT
    fall back to all facts — ``fact_graph_content`` raises ``TargetUnsetError`` and
    ``server.paper_write`` returns a ``needs_target`` result. The deepest-terminal
    facts are not a fallback here; they are only the ``danus finalize``
    suggestion (see ``_terminal_facts``)."""
    if headline:
        return list(headline), "arg"
    from_brief = brief_headline_fact_ids(project_dir, paper_id)
    if from_brief:
        return from_brief, "brief"
    from_target = target_fact_ids(Path(project_dir), paper_id)
    if from_target:
        return from_target, "target"
    return [], "unset"



# --------------------------------------------------------------------------- #
# fact-graph content (writer only)                                            #
# --------------------------------------------------------------------------- #

def _toposort_with_predecessors(fg: FactGraph, seeds: Optional[List[str]]) -> List[str]:
    """Return the fact ids to embed, topologically ordered (predecessors first).

    ``seeds=None`` → all facts. Otherwise the given facts plus their transitive
    predecessors. Same order in both cases: a stable topological sort so a fact
    always follows every fact it depends on.
    """
    all_ids = fg.list()
    known = set(all_ids)

    if seeds is None:
        wanted = list(all_ids)
    else:
        wanted_set: set = set()
        frontier = list(seeds)
        while frontier:
            fid = frontier.pop()
            if fid in wanted_set:
                continue
            if fid not in known:
                raise ValueError(f"unknown fact id in headline: {fid!r}")
            wanted_set.add(fid)
            frontier.extend(fg.predecessors(fid))
        wanted = [fid for fid in all_ids if fid in wanted_set]

    # Kahn-style stable topological sort over the induced subgraph. Ties break by
    # the sorted-id order from ``fg.list()`` so the output is deterministic.
    wanted_set = set(wanted)
    preds_in = {fid: [p for p in fg.predecessors(fid) if p in wanted_set] for fid in wanted}
    ordered: List[str] = []
    placed: set = set()
    remaining = list(wanted)  # already in sorted-id order
    progressed = True
    while remaining and progressed:
        progressed = False
        still: List[str] = []
        for fid in remaining:
            if all(p in placed for p in preds_in[fid]):
                ordered.append(fid)
                placed.add(fid)
                progressed = True
            else:
                still.append(fid)
        remaining = still
    # A cycle (should not happen in a verified DAG) leaves ``remaining``; append
    # deterministically rather than dropping facts.
    ordered.extend(remaining)
    return ordered


def _body_sections(raw: str) -> str:
    """The fact's body with the YAML frontmatter stripped — the shared scrub
    (``authoring.common.body_sections``). Stripping the frontmatter here keeps
    ``fact_id`` / ``author`` / ``problem_id`` / ``glossary_introduces`` /
    ``external_refs`` out of the codex-facing prompt; the body math is preserved
    verbatim. (The predecessor DAG line is re-added by ``_fact_block`` — the paper
    legitimately needs it for internal ``\\ref`` cross-references.)"""
    return body_sections(raw)


def _fact_block(fg: FactGraph, fid: str) -> str:
    """Embed one fact's **body** (``## statement`` / ``## proof`` / ``## intuition``)
    plus its predecessor DAG. The predecessor line is kept explicitly — the paper
    legitimately needs the DAG structure to build internal ``\\ref`` cross-references
    — but the fact's frontmatter (``fact_id`` / ``author`` / ``problem_id`` / …) is
    stripped so it never reaches the paper codex. The body math is preserved
    verbatim; never summarize a proof."""
    raw = fg.get_raw(fid) or ""
    preds = parse_frontmatter(raw)["predecessors"]  # type: ignore[index]
    pred_line = ", ".join(preds) if preds else "(none)"
    header = f"[source_fact: {fid}]\npredecessors (DAG): {pred_line}\n"
    return header + "\n" + _body_sections(raw)


def _statement_block(fg: FactGraph, fid: str) -> str:
    """Embed one fact's STATEMENT ONLY (never the proof/intuition) plus its
    predecessor DAG and its ``[source_fact: <id>]`` tag.

    Reuses ``core.statement_of`` (the one-line ``## statement`` snippet) and the
    same header shape as ``_fact_block`` (tag + predecessor DAG line), so the
    planner can plan cross-refs (via the DAG) and assign facts to sections (via the
    id) WITHOUT the full proofs — which is what keeps the planning pass small enough
    to fit a very large closure in one context window."""
    raw = fg.get_raw(fid) or ""
    preds = parse_frontmatter(raw)["predecessors"]  # type: ignore[index]
    pred_line = ", ".join(preds) if preds else "(none)"
    header = f"[source_fact: {fid}]\npredecessors (DAG): {pred_line}\n"
    stmt = statement_of(raw).strip()
    return header + "\n## statement\n" + (stmt if stmt else "(empty statement)") + "\n"


def statements_only_content(project_dir: Path, headline: Optional[List[str]] = None,
                            paper_id: Optional[str] = None) -> str:
    """The closure as STATEMENTS ONLY — each selected fact's ``[source_fact]`` tag +
    predecessor DAG + one-line ``## statement`` (NO proof, NO intuition),
    topologically ordered. Same target-closure selection as ``fact_graph_content``
    (arg > brief > TARGET.md; ``TargetUnsetError`` on unset), but the bodies are the
    statements only. This is the planner's fact input — small enough for a large
    closure to fit one context window (proofs are added per-section in phase 2)."""
    project_dir = Path(project_dir)
    fg = FactGraph(project_dir)
    if headline is None:
        headline, source = resolve_headline(project_dir, None, paper_id)
        if source == "unset":
            raise TargetUnsetError(
                "no paper target is set: pass an explicit headline, set "
                "headline_fact_ids in PROJECT_BRIEF.md, or run "
                "`danus finalize <project> <fact_id>` to record TARGET.md"
            )
    ids = _toposort_with_predecessors(fg, headline)
    if not ids:
        return "_(no verified facts found in the project fact graph)_\n"
    blocks = [_statement_block(fg, fid) for fid in ids]
    return "\n".join(blocks)


def closure_order(project_dir: Path, headline: Optional[List[str]] = None,
                  paper_id: Optional[str] = None) -> List[str]:
    """The ordered closure fact ids (topological, predecessors first) for the
    resolved target — the SAME selection ``fact_graph_content`` /
    ``statements_only_content`` embed. Raises ``TargetUnsetError`` on an unset
    target (``headline is None`` + no brief/TARGET.md). ``paper_chunked`` uses this
    to enumerate the closure for the coverage check and to slice facts per section."""
    project_dir = Path(project_dir)
    fg = FactGraph(project_dir)
    if headline is None:
        headline, source = resolve_headline(project_dir, None, paper_id)
        if source == "unset":
            raise TargetUnsetError(
                "no paper target is set: pass an explicit headline, set "
                "headline_fact_ids in PROJECT_BRIEF.md, or run "
                "`danus finalize <project> <fact_id>` to record TARGET.md"
            )
    return _toposort_with_predecessors(fg, headline)


def full_bodies_for(project_dir: Path, fact_ids: List[str]) -> str:
    """Render the FULL bodies (``[source_fact]`` tag + predecessor DAG +
    statement/proof/intuition) for exactly ``fact_ids``, in the given order, joined
    the same way ``fact_graph_content`` joins its blocks. Used by ``paper_chunked``
    to embed ONE section's facts (proofs included). Empty list → a clear sentinel."""
    fg = FactGraph(Path(project_dir))
    if not fact_ids:
        return "_(this section has no assigned facts — write only its prose)_\n"
    return "\n".join(_fact_block(fg, fid) for fid in fact_ids)


def citation_map(project_dir: Path, headline: Optional[List[str]] = None,
                 paper_id: Optional[str] = None) -> str:
    """The PUBLISHED references the target closure's facts already cite (each fact's
    ``external_refs``), each with what it establishes (``cited_for``). This is the
    "cite, don't re-prove" map: for a STANDARD / already-published supporting result,
    the writer/reviser cites the matching reference (the fact graph proved that step by
    citing this very paper) instead of proving it. Deduped by key; ``""`` on an unset
    target / no external refs (so callers can skip the section)."""
    from danus.core.factgraph import parse_frontmatter
    project_dir = Path(project_dir)
    fg = FactGraph(project_dir)
    if headline is None:
        headline, source = resolve_headline(project_dir, None, paper_id)
        if source == "unset":
            return ""
    try:
        ids = _toposort_with_predecessors(fg, headline)
    except Exception:  # noqa: BLE001
        return ""
    refs: Dict[str, Dict[str, object]] = {}
    for fid in ids:
        for r in parse_frontmatter(fg.get_raw(fid) or "")["external_refs"]:  # type: ignore[index]
            key = r.get("key")
            if not key:
                continue
            e = refs.setdefault(key, {"title": r.get("title", ""),
                                      "arxiv": r.get("arxiv", ""), "cited_for": []})
            cf = (r.get("cited_for") or "").strip()
            if cf and cf not in e["cited_for"]:  # type: ignore[operator]
                e["cited_for"].append(cf)  # type: ignore[attr-defined]
    if not refs:
        return ""
    lines: List[str] = []
    for key in sorted(refs):
        e = refs[key]
        head = f"[{key}] {e['title']}".rstrip()
        if e["arxiv"]:
            head += f" (arXiv:{e['arxiv']})"
        lines.append(head)
        for cf in list(e["cited_for"])[:4]:  # type: ignore[index]
            lines.append(f"    establishes: {cf}")
    return "\n".join(lines)


def statements_for(project_dir: Path, fact_ids: List[str]) -> str:
    """Render STATEMENTS ONLY (``[source_fact]`` tag + predecessor DAG + one-line
    statement) for exactly ``fact_ids``, in the given order. Used by
    ``paper_chunked`` to embed every OTHER section's results as \\ref context. Empty
    list → a clear sentinel."""
    fg = FactGraph(Path(project_dir))
    if not fact_ids:
        return "_(no other closure facts)_\n"
    return "\n".join(_statement_block(fg, fid) for fid in fact_ids)


def section_ref_context_ids(project_dir: Path,
                            section_fact_ids: List[str],
                            order: List[str]) -> List[str]:
    """The ids whose STATEMENTS one section needs as ``\\ref`` context: the DIRECT
    predecessors (the DAG edges) of the section's OWN facts, minus the section's own
    facts, ordered by ``order`` (the coverage order) for coherent reading.

    This is deliberately BOUNDED and LOCAL — a section embeds only the statements it
    actually ``\\ref``s, never every other closure fact. Embedding the whole closure's
    statements in every section would make a single section's prompt
    exceed the codex input hard-limit on a deep closure (~470 facts → 1.4M chars).
    A fact's proof only ``\\ref``s its DAG predecessors, and in whole-closure mode
    every predecessor is itself a rendered result, so direct predecessors are exactly
    the cross-references the writer needs to phrase. Empty → sentinel handled by
    ``statements_for``."""
    fg = FactGraph(Path(project_dir))
    exclude = set(section_fact_ids)
    want: set = set()
    for fid in section_fact_ids:
        for p in fg.predecessors(fid):
            if p not in exclude:
                want.add(p)
    pos = {f: i for i, f in enumerate(order)}
    return sorted(want, key=lambda f: pos.get(f, len(order)))


def selected_partition(project_dir: Path,
                       fact_ids: List[str]) -> Tuple[List[str], List[str]]:
    """Partition a MAIN-AGENT-SELECTED fact set into ``(ordered_selected,
    referenced_ids)`` for the single-pass writer.

    ``ordered_selected`` — exactly the given ``fact_ids`` in a globally-consistent
    topological order (predecessors first), WITHOUT expanding to their closure. These
    are the results the paper PRESENTS in full (statement + proof).

    ``referenced_ids`` — the DIRECT predecessors of the selected set that the main
    agent did NOT select (``∪ predecessors(f) − selected``), topologically ordered.
    These are embedded as STATEMENTS ONLY so the writer can ``\\ref``/``\\cite`` them
    without re-proving — the editorial act (a real paper cites its granular lemmas,
    it does not reproduce them). Bounded by the selection, not the whole closure —
    which is what keeps a curated subset within one context window.

    Raises ``ValueError`` if any id is not in the fact graph (a typo / stale id from
    the main agent). Membership in the target closure is NOT enforced here — that is
    a soft warning at the ``server.paper_write`` layer (it has the headline)."""
    fg = FactGraph(Path(project_dir))
    known = set(fg.list())
    unknown = [f for f in fact_ids if f not in known]
    if unknown:
        raise ValueError(f"unknown fact id(s) in fact_ids: {unknown}")
    # a single global topological order (predecessors first) to sort both subsets by.
    global_order = _toposort_with_predecessors(fg, None)
    sel = set(fact_ids)
    ordered_selected = [f for f in global_order if f in sel]
    ref: set = set()
    for f in fact_ids:
        for p in fg.predecessors(f):
            if p not in sel:
                ref.add(p)
    referenced_ids = [f for f in global_order if f in ref]
    return ordered_selected, referenced_ids


def subgraph_skeleton(project_dir: Path, headline: Optional[List[str]] = None,
                      paper_id: Optional[str] = None) -> Dict[str, object]:
    """A COMPACT, deterministic skeleton of the target closure for the main agent to
    read and SELECT from — statements only, no proofs, no codex.

    For each fact in the resolved target closure (topological order, via
    ``closure_order`` — same selection the writer would embed) produce a small
    record: ``{id, statement (one-line), predecessors (in-closure DAG edges),
    dependents (in-closure in-degree — how load-bearing it is), glossary_introduces
    (the symbols it introduces)}``. The whole thing is bounded by statements, so a
    several-hundred-fact closure still fits the main agent's context — where the full
    proofs would not.

    Raises ``TargetUnsetError`` on an unset target (propagated from ``closure_order``);
    the ``server.paper_subgraph`` tool turns that into a ``needs_target`` envelope."""
    project_dir = Path(project_dir)
    fg = FactGraph(project_dir)
    ids = closure_order(project_dir, headline, paper_id)
    id_set = set(ids)
    dependents: Dict[str, int] = {fid: 0 for fid in ids}
    preds_by: Dict[str, List[str]] = {}
    for fid in ids:
        preds = [p for p in fg.predecessors(fid) if p in id_set]
        preds_by[fid] = preds
        for p in preds:
            dependents[p] += 1
    facts: List[Dict[str, object]] = []
    for fid in ids:
        raw = fg.get_raw(fid) or ""
        gi = parse_frontmatter(raw)["glossary_introduces"]  # type: ignore[index]
        facts.append({
            "id": fid,
            "statement": statement_of(raw).strip(),
            "predecessors": preds_by[fid],
            "dependents": dependents[fid],
            "glossary_introduces": sorted(gi.keys()) if isinstance(gi, dict) else [],
        })
    return {"count": len(facts), "facts": facts}


def fact_graph_content(project_dir: Path, headline: Optional[List[str]] = None,
                       paper_id: Optional[str] = None) -> str:
    """The writer's authoritative mathematics: each selected fact's full body
    (statement / proof / intuition) plus its predecessor DAG, topologically
    ordered.

    The target is the RECORDED headline, resolved via ``resolve_headline``
    (arg > brief > ``<project>/TARGET.md``): only that set's transitive-predecessor
    closure is embedded — so proven-but-unused side lemmas are excluded and the
    writer's facts match the ledger's closure.

    When ``headline is None`` and the target resolves to ``"unset"`` (no arg, no
    brief field, no finalized TARGET.md), this RAISES ``TargetUnsetError`` rather
    than silently embedding all facts — the pipeline refuses to guess. Pass an
    explicit ``headline`` to override; an explicit empty ``headline=[]`` yields the
    no-facts sentinel (used for genuinely empty graphs)."""
    project_dir = Path(project_dir)
    fg = FactGraph(project_dir)
    if headline is None:
        headline, source = resolve_headline(project_dir, None, paper_id)
        if source == "unset":
            raise TargetUnsetError(
                "no paper target is set: pass an explicit headline, set "
                "headline_fact_ids in PROJECT_BRIEF.md, or run "
                "`danus finalize <project> <fact_id>` to record TARGET.md"
            )
    ids = _toposort_with_predecessors(fg, headline)
    if not ids:
        return "_(no verified facts found in the project fact graph)_\n"
    blocks = [_fact_block(fg, fid) for fid in ids]
    return "\n".join(blocks)


# --------------------------------------------------------------------------- #
# optional structural exemplar (writer only)                                  #
# --------------------------------------------------------------------------- #

def _anchor_block(anchor: Optional[str]) -> Optional[str]:
    """Embed one operator-supplied STRUCTURAL exemplar from
    ``style/anchors/<anchor>/`` (its text files, verbatim). Returns None when no
    exemplar is named or the dir is empty/absent — the exemplar is strictly
    optional (voice comes from the unified STYLE_GUIDE; this only supplies ONE
    structure to imitate, chosen deterministically by the brief's
    ``structural_exemplar`` field)."""
    if not anchor:
        return None
    adir = skill_dir() / "style" / "anchors" / anchor
    if not adir.is_dir():
        return None
    parts: List[str] = []
    for path in sorted(adir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # A binary exemplar (e.g. a .pdf) cannot be embedded verbatim as text;
            # name it so the writer knows it exists on disk (it has an empty cwd,
            # so this is informational only).
            parts.append(f"--- {path.relative_to(adir)} (binary; not embedded) ---")
            continue
        parts.append(f"--- {path.relative_to(adir)} ---\n{text.rstrip()}")
    return "\n\n".join(parts) if parts else None


# --------------------------------------------------------------------------- #
# per-role assemblers                                                          #
# --------------------------------------------------------------------------- #

def build_writer_prompt(
    project_dir: Path,
    *,
    headline: Optional[List[str]] = None,
    paper_id: Optional[str] = None,
    fact_ids: Optional[List[str]] = None,
    instructions: Optional[str] = None,
) -> str:
    """Writer input set (isolation contract): AGENTS.md + PAPER_WRITER_PROMPT +
    STYLE_GUIDE + PAPER_STRUCTURE + acknowledgement boilerplate; PROJECT_BRIEF +
    optional MAIN_AGENT_INSTRUCTIONS + REFERENCE_LEDGER + the fact-graph math +
    optionally ONE structural exemplar.

    Voice comes from the unified STYLE_GUIDE (distilled across all anchors). The
    structural exemplar is OPTIONAL, exactly ONE, chosen DETERMINISTICALLY: the
    brief's ``structural_exemplar`` field names the anchor folder to imitate for
    STRUCTURE, embedded iff the brief names it and it exists (blank/absent = none).

    Fact content — two modes:
      * ``fact_ids is None`` (legacy): the whole target CLOSURE in full (see
        ``fact_graph_content``), byte-for-byte unchanged from before.
      * ``fact_ids`` given (the main agent's SELECTION): only the selected facts in
        FULL (``SELECTED_FACTS``) plus their direct-predecessor STATEMENTS
        (``REFERENCED_FACTS`` — ``\\ref``/``\\cite`` context, never re-proved). This
        is how a curated subset stays within one context window.

    ``instructions`` — the main agent's editorial direction (sectioning, emphasis,
    what to foreground), embedded as an authoritative ``MAIN_AGENT_INSTRUCTIONS``
    block after the brief; a plain string, so it carries no fact ids into the .tex."""
    project_dir = Path(project_dir)
    ws = paper_workspace(project_dir, paper_id)
    brief_rel = str((ws / "PROJECT_BRIEF.md").relative_to(project_dir))
    ledger_rel = str((ws / "REFERENCE_LEDGER.md").relative_to(project_dir))
    parts = [
        "You are the PAPER WRITER. Everything you need is embedded below; you have "
        "no filesystem to read. Produce a single complete main.tex per the "
        "contract and role prompt.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("PAPER_WRITER_PROMPT.md", _read_fixed("roles/PAPER_WRITER_PROMPT.md")),
        section("STYLE_GUIDE.md", _read_fixed("style/STYLE_GUIDE.md")),
        section("PAPER_STRUCTURE.md", _read_fixed("style/PAPER_STRUCTURE.md")),
        section("ACKNOWLEDGEMENT_BOILERPLATE.md", _read_fixed("boilerplate/acknowledgement.md")),
        section("PROJECT_BRIEF.md", _read_project(project_dir, brief_rel)),
    ]
    if instructions and instructions.strip():
        parts.append(section("MAIN_AGENT_INSTRUCTIONS", instructions.strip()))
    parts.append(section("REFERENCE_LEDGER.md", _read_project(project_dir, ledger_rel)))
    if fact_ids:
        ordered_selected, _referenced = selected_partition(project_dir, fact_ids)
        # The writer gets ONLY the main-agent-selected IMPORTANT facts, in full. It
        # proves these and weaves in / glosses the minor supporting steps; it must NOT
        # introduce a bare unproved lemma (that dangling is what fails whole-document
        # verification). Small routine gaps are acceptable; if the verifier flags a
        # gap as a genuine missing lemma, the main agent adds that fact to the
        # selection and re-writes (orchestration loop).
        parts.append(section(
            "SELECTED_FACTS (the important results to PRESENT and PROVE, in full)",
            full_bodies_for(project_dir, ordered_selected)))
        # "Cite, don't re-prove": for a STANDARD supporting result the selected proofs
        # rely on but that is already PUBLISHED, cite the matching reference (with the
        # precise theorem it gives) instead of proving it — the path to a self-contained-
        # modulo-citations paper the whole-doc verifier accepts.
        cmap = citation_map(project_dir, headline, paper_id)
        if cmap:
            parts.append(section(
                "PUBLISHED_CITATIONS (cite these for standard/published supporting "
                "results — exact key + what each establishes; add a \\bibitem; do NOT "
                "re-prove them. Prove only the SELECTED_FACTS)", cmap))
    else:
        parts.append(section("FACT_GRAPH_CONTENT",
                             fact_graph_content(project_dir, headline, paper_id)))
    # Structural exemplar: read deterministically from the brief (never a free
    # per-call arg). Embedded only when the brief names one and it exists on disk.
    exemplar = brief_structural_exemplar(project_dir, paper_id)
    exemplar_body = _anchor_block(exemplar)
    if exemplar_body is not None:
        parts.append(section(f"STRUCTURAL_EXEMPLAR ({exemplar})", exemplar_body))
    return "".join(parts)


# --------------------------------------------------------------------------- #
# chunked-generation prompt builders (P0 — large-closure paper generation)     #
# --------------------------------------------------------------------------- #
#
# When a closure's full-proof writer prompt would overflow the model context
# window, ``paper_chunked`` generates the paper in three phases: PLAN (statements
# only) -> per-SECTION fill (this section's full proofs + others' statements) ->
# STITCH (deterministic Python). These two builders assemble the planner and
# section-writer prompts, keeping ALL prompt assembly in this module (deterministic
# + testable), symmetric to the single-pass ``build_writer_prompt``. The
# non-agentic isolation invariant is preserved: everything is embedded, output IS
# the text, no tool calls, empty cwd.


def build_planner_prompt(
    project_dir: Path,
    *,
    headline: Optional[List[str]] = None,
    paper_id: Optional[str] = None,
    fact_ids: Optional[List[str]] = None,
    instructions: Optional[str] = None,
) -> str:
    """Phase-1 PLANNER input set: AGENTS.md + PAPER_PLANNER_PROMPT + STYLE_GUIDE +
    PAPER_STRUCTURE + acknowledgement boilerplate; PROJECT_BRIEF + optional
    MAIN_AGENT_INSTRUCTIONS + REFERENCE_LEDGER + the facts as **STATEMENTS ONLY**
    (id-tag + predecessor DAG + one-line statement per fact, NO proofs). No full
    proofs here — that is what keeps this pass small enough for a very large set. The
    planner emits the fixed preamble/front matter, a section plan assigning every
    fact, and the bibliography (see ``PAPER_PLANNER_PROMPT.md`` §3–4).

    Fact scope mirrors the single-pass writer: ``fact_ids`` given → the main agent's
    SELECTION (the chunked fallback partitions exactly that curated set); else the
    whole target closure. ``instructions`` is the main agent's editorial direction
    (sectioning/emphasis), embedded so the section plan respects it."""
    project_dir = Path(project_dir)
    ws = paper_workspace(project_dir, paper_id)
    brief_rel = str((ws / "PROJECT_BRIEF.md").relative_to(project_dir))
    ledger_rel = str((ws / "REFERENCE_LEDGER.md").relative_to(project_dir))
    if fact_ids:
        ordered_selected, _referenced = selected_partition(project_dir, fact_ids)
        closure_statements = statements_for(project_dir, ordered_selected)
    else:
        closure_statements = statements_only_content(project_dir, headline, paper_id)
    parts = [
        "You are the PAPER PLANNER. Everything you need is embedded below; you have "
        "no filesystem to read. This paper is generated section-by-section because "
        "its closure is too large for one pass. Produce the fixed preamble, front "
        "matter, section plan, and bibliography per the contract and role prompt.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("PAPER_PLANNER_PROMPT.md", _read_fixed("roles/PAPER_PLANNER_PROMPT.md")),
        section("STYLE_GUIDE.md", _read_fixed("style/STYLE_GUIDE.md")),
        section("PAPER_STRUCTURE.md", _read_fixed("style/PAPER_STRUCTURE.md")),
        section("ACKNOWLEDGEMENT_BOILERPLATE.md", _read_fixed("boilerplate/acknowledgement.md")),
        section("PROJECT_BRIEF.md", _read_project(project_dir, brief_rel)),
    ]
    if instructions and instructions.strip():
        parts.append(section("MAIN_AGENT_INSTRUCTIONS", instructions.strip()))
    parts.append(section("REFERENCE_LEDGER.md", _read_project(project_dir, ledger_rel)))
    parts.append(section("CLOSURE_STATEMENTS", closure_statements))
    return "".join(parts)


def build_section_writer_prompt(
    project_dir: Path,
    *,
    section_title: str,
    section_label: str,
    section_facts: str,
    other_statements: str,
    preamble_frontmatter: str,
    section_plan: str,
    paper_id: Optional[str] = None,
) -> str:
    """Phase-2 SECTION-WRITER input set for ONE section: AGENTS.md +
    PAPER_SECTION_WRITER_PROMPT + STYLE_GUIDE + PAPER_STRUCTURE; PROJECT_BRIEF +
    REFERENCE_LEDGER + the FIXED preamble+front matter (macro/label consistency) +
    the whole section plan (titles+labels, so cross-section ``\\ref`` resolves) +
    THIS section's facts in FULL (``section_facts`` — statement/proof/intuition +
    ``[source_fact]`` tag) + every OTHER closure fact's STATEMENT ONLY with the
    section/label it lives in (``other_statements``) + this section's title/label.

    ``paper_chunked`` assembles the four dynamic bodies (per-section facts, other
    statements, the fixed preamble/front matter, the section-plan digest); this
    builder just frames them, keeping assembly deterministic + in one module. The
    section writer outputs THIS section's LaTeX + a ``%%%PROVENANCE%%%`` map (see
    ``PAPER_SECTION_WRITER_PROMPT.md`` §3)."""
    project_dir = Path(project_dir)
    ws = paper_workspace(project_dir, paper_id)
    brief_rel = str((ws / "PROJECT_BRIEF.md").relative_to(project_dir))
    ledger_rel = str((ws / "REFERENCE_LEDGER.md").relative_to(project_dir))
    parts = [
        "You are the PAPER SECTION WRITER. Everything you need is embedded below; "
        "you have no filesystem to read. The preamble, front matter, section plan, "
        "and bibliography are already FIXED by the planner — write ONLY this "
        "section's body per the contract and role prompt.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("PAPER_SECTION_WRITER_PROMPT.md", _read_fixed("roles/PAPER_SECTION_WRITER_PROMPT.md")),
        section("STYLE_GUIDE.md", _read_fixed("style/STYLE_GUIDE.md")),
        section("PAPER_STRUCTURE.md", _read_fixed("style/PAPER_STRUCTURE.md")),
        section("PROJECT_BRIEF.md", _read_project(project_dir, brief_rel)),
        section("REFERENCE_LEDGER.md", _read_project(project_dir, ledger_rel)),
        section("FIXED_PREAMBLE_AND_FRONTMATTER (reference only — do NOT re-emit)",
                preamble_frontmatter),
        section("SECTION_PLAN (all sections' titles+labels, in order)", section_plan),
        section(f"THIS_SECTION (title={section_title!r}, label={section_label!r})",
                f"Write \\section{{{section_title}}}\\label{{{section_label}}} and its body."),
        section("THIS_SECTION_FACTS (full bodies — render these)", section_facts),
        section("OTHER_CLOSURE_FACTS (STATEMENTS ONLY — \\ref these, never re-prove)",
                other_statements),
    ]
    return "".join(parts)


def _ws_rel(project_dir: Path, paper_id: Optional[str], name: str) -> str:
    """The project-relative path of ``<paper workspace>/<name>`` — the arg
    ``_read_project`` (which joins onto ``project_dir``) expects. Default paper →
    ``paper/<name>``; else ``papers/<paper_id>/<name>``."""
    ws = paper_workspace(Path(project_dir), paper_id)
    return str((ws / name).relative_to(Path(project_dir)))


def build_paper_math_verifier_prompt(project_dir: Path, *,
                                     paper_id: Optional[str] = None) -> str:
    """The THIRD verifier's input set (isolation contract): AGENTS.md +
    PAPER_MATH_VERIFIER_PROMPT + the paper's whole mathematical development
    (``main.tex``) + the verified REFERENCE_LEDGER. It gets NO fact graph and NO
    style/structure. This is a SEPARATE verifier from the fact-submission verifier
    (``danus/verify``) and the reference verifier (``reference_verify``): its policy
    TRUSTS the ledger's confirmed precise external citations and scrutinizes only the
    paper's own reasoning + self-containedness — so its (looser-on-citations) stance
    changes paper delivery ONLY, never fact verification."""
    project_dir = Path(project_dir)
    parts = [
        "You are the PAPER MATH VERIFIER (a dedicated third verifier). Judge whether "
        "the whole paper below correctly and self-containedly establishes its main "
        "result, TRUSTING the confirmed precise citations in the ledger and "
        "scrutinizing the paper's own reasoning. Everything you need is embedded.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("PAPER_MATH_VERIFIER_PROMPT.md", _read_fixed("roles/PAPER_MATH_VERIFIER_PROMPT.md")),
        section("REFERENCE_LEDGER.md (citations already CONFIRMED by the reference verifier — trust the `verified-by: verifier` rows)",
                _read_project(project_dir, _ws_rel(project_dir, paper_id, "REFERENCE_LEDGER.md"))),
        section("PAPER (the whole main.tex — read the mathematics in order)",
                _read_project(project_dir, _ws_rel(project_dir, paper_id, "main.tex"))),
    ]
    return "".join(parts)


def build_auditor_prompt(project_dir: Path, *, paper_id: Optional[str] = None) -> str:
    """Auditor input set (isolation contract): AGENTS.md + REFERENCE_AUDITOR_PROMPT;
    main.tex + REFERENCE_LEDGER. It must NOT receive the fact graph, STYLE_GUIDE,
    or PAPER_STRUCTURE. It flags only; live online verification of the flags is
    ``reference_verify``'s job (the reference verifier); the auditor codex has no tools/network."""
    project_dir = Path(project_dir)
    parts = [
        "You are the REFERENCE AUDITOR. You have no live tools and no network; you "
        "FLAG entries, you do not verify them online (the reference verifier / reference_verify does that). "
        "Everything you need is embedded below.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("REFERENCE_AUDITOR_PROMPT.md", _read_fixed("roles/REFERENCE_AUDITOR_PROMPT.md")),
        section("main.tex", _read_project(project_dir, _ws_rel(project_dir, paper_id, "main.tex"))),
        section("REFERENCE_LEDGER.md", _read_project(project_dir, _ws_rel(project_dir, paper_id, "REFERENCE_LEDGER.md"))),
    ]
    return "".join(parts)


def build_verifier_prompt(project_dir: Path, *, findings: Optional[str] = None,
                          paper_id: Optional[str] = None) -> str:
    """Reference-verifier input set (isolation contract): AGENTS.md +
    REFERENCE_VERIFIER_PROMPT; ``main.tex``'s bibliography + every ``\\cite`` (we
    embed the whole ``main.tex`` — the verifier needs the bibliography section and
    all ``\\cite``/``\\note`` sites) + REFERENCE_LEDGER + the auditor's findings.

    It MUST NOT receive the fact graph, STYLE_GUIDE, or PAPER_STRUCTURE. This is the
    ONLINE half of the chain: unlike the auditor codex (offline, flags only), the
    verifier codex is driven over the NETWORKED path (``driver.run_codex(
    networked=True)`` — gateway ``search_arxiv_theorems`` + web_search) and verifies
    each flagged entry against an authoritative source. The orchestrator updates the
    ledger in place from its verdicts, never ``main.tex`` (the reviser's job)."""
    project_dir = Path(project_dir)
    findings_body = (findings or "").strip() or (
        "_(no auditor findings passed; verify every ledger row still marked "
        "`verified-by: unverified` and every `\\note{[cite/blocker]}` in main.tex)_"
    )
    parts = [
        "You are the REFERENCE VERIFIER. You HAVE network: search_arxiv_theorems "
        "(gateway) + web_search. Verify ONLY the entries the auditor flagged, "
        "against an authoritative source. You emit one verdict per entry (the "
        "orchestrator updates REFERENCE_LEDGER.md in place from them); you "
        "do NOT touch main.tex (that is the reviser's job). Everything you need is "
        "embedded below.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("REFERENCE_VERIFIER_PROMPT.md", _read_fixed("roles/REFERENCE_VERIFIER_PROMPT.md")),
        section("main.tex", _read_project(project_dir, _ws_rel(project_dir, paper_id, "main.tex"))),
        section("REFERENCE_LEDGER.md", _read_project(project_dir, _ws_rel(project_dir, paper_id, "REFERENCE_LEDGER.md"))),
        section("AUDITOR_FINDINGS", findings_body),
    ]
    return "".join(parts)


def build_reviser_prompt(
    project_dir: Path,
    *,
    compile_log: Optional[str] = None,
    notes: Optional[str] = None,
    citation_fixes: Optional[str] = None,
    gap_fill: Optional[str] = None,
    paper_id: Optional[str] = None,
) -> str:
    """Reviser input set (isolation contract): AGENTS.md + PAPER_REVISER_PROMPT +
    STYLE_GUIDE; main.tex + REVISION_LOG (tail) + the trigger (compile_log,
    citation_fixes, notes, and/or gap_fill). It must NOT receive the fact graph.

    ``citation_fixes`` is the verify→revise seam: the verifier's one-line
    replacement suggestions per entry, passed as its OWN labelled trigger block
    (distinct from operator ``notes``); the reviser applies them against
    ``\\bibitem``/ledger keys already present, never invented.

"""
    project_dir = Path(project_dir)
    parts = [
        "You are the PAPER REVISER. Everything you need is embedded below; you have "
        "no filesystem to read. Revise the embedded main.tex per the contract, the "
        "role prompt, and the trigger below.",
        section("AGENTS.md", _read_fixed("roles/AGENTS.md")),
        section("PAPER_REVISER_PROMPT.md", _read_fixed("roles/PAPER_REVISER_PROMPT.md")),
        section("STYLE_GUIDE.md", _read_fixed("style/STYLE_GUIDE.md")),
        section("main.tex", _read_project(project_dir, _ws_rel(project_dir, paper_id, "main.tex"))),
        section("REVISION_LOG.md (tail)", _revision_log_tail(project_dir, paper_id)),
        section("TRIGGER", _reviser_trigger(compile_log, notes, citation_fixes, gap_fill)),
    ]
    return "".join(parts)


def _revision_log_tail(project_dir: Path, paper_id: Optional[str] = None,
                       max_chars: int = 8000) -> str:
    """The last portion of the paper's REVISION_LOG.md (newest entries are on top
    per the template, so the head is the recent tail), rooted at the per-paper
    workspace. Absent log → a clear note; never fail — the log is optional context,
    not a required input."""
    path = paper_workspace(project_dir, paper_id) / "REVISION_LOG.md"
    if not path.is_file():
        return "_(no REVISION_LOG.md yet — this is an early round)_"
    text = path.read_text(encoding="utf-8")
    return text if len(text) <= max_chars else text[:max_chars] + "\n… (truncated)\n"


def _reviser_trigger(compile_log: Optional[str], notes: Optional[str],
                     citation_fixes: Optional[str] = None,
                     gap_fill: Optional[str] = None) -> str:
    """Build the reviser's TRIGGER block, prefixed with an explicit ``MODE:`` line
    the role prompt branches on (§3a/§8):

      - ``compile-fix``   — only a ``compile_log`` is present: fix ONLY the compile errors.
      - ``compile-fix+targeted`` — a ``compile_log`` AND ``notes``/``citation_fixes``
        are present (the compile-retry of a targeted round): fix the compile errors
        AND STILL apply the pending citation_fixes/notes — do NOT defer them (that
        silent-drop was the bug this mode fixes).
      - ``gap-fill`` — ``gap_fill`` present (the whole-document verify→revise seam):
        the whole-doc verifier flagged the paper as not self-contained; the MAIN
        AGENT has chosen FACTS to add and passed the verifier's feedback + its own
        guidance + those facts' verified statements/proofs. The reviser INCORPORATES
        them — proving the missing lemmas into the paper (inline where natural, or as
        new labelled results) so the development becomes self-contained. This mode MAY
        add new formal content (that is its purpose). Combined with a ``compile_log``
        it becomes ``gap-fill+compile-fix``.
      - ``targeted-notes`` — ``notes`` and/or ``citation_fixes`` present (no compile
        log): act ONLY on those items (+ minimal adjacent fixes).
      - ``style-audit-pass`` — nothing passed: the global style rewrite.

    ``citation_fixes`` / ``gap_fill`` are each their OWN labelled
    block. ``gap_fill`` (assembled by ``server.paper_revise`` from the whole-doc
    verifier feedback + the main agent's chosen facts) is the single verify→revise
    seam: it carries verifier opinion + main-agent opinion + facts, together."""
    if gap_fill and compile_log:
        mode = "gap-fill+compile-fix"
    elif gap_fill:
        mode = "gap-fill"
    elif compile_log and (notes or citation_fixes):
        mode = "compile-fix+targeted"
    elif compile_log:
        mode = "compile-fix"
    elif notes or citation_fixes:
        mode = "targeted-notes"
    else:
        mode = "style-audit-pass"
    parts: List[str] = [f"MODE: {mode}"]
    if gap_fill:
        parts.append(
            "--- gap_fill (the whole-document verifier said the paper is NOT "
            "self-contained; below is the verifier's feedback, the main agent's "
            "guidance, and the VERIFIED statements/proofs of the facts the main agent "
            "chose to add. INCORPORATE them: prove the missing lemmas into the paper "
            "— inline where natural, or as new labelled results — so the development "
            "becomes self-contained. Adapt to the paper's notation; keep existing "
            "\\label targets valid; never emit a fact id or a fabricated citation. "
            "Emit your changes as a PATCH of find/replace edits per the output "
            "contract — an insertion is a find/replace whose replacement re-includes "
            "the anchor.\n"
            "HOW MUCH TO WRITE OUT (this is what decides whether the paper passes the "
            "whole-paper verifier). The verifier accepts a step only if it is (a) "
            "derived in the paper, (b) backed by a precise citation to a confirmed "
            "reference, or (c) a genuinely routine/standard computation a competent "
            "reader completes unaided. It REJECTS — as an unproved gap — any "
            "LOAD-BEARING, non-obvious step that is asserted or waved away with a "
            "summarizing phrase ('by the same argument', 'a high-level appeal to the "
            "... computation', 'analogously', 'similarly', 'it follows that') IN PLACE "
            "OF the actual derivation. The supplied proofs below are already verified "
            "and correct, so for every such load-bearing step WRITE OUT the derivation "
            "they give you (the specific computation, inequality, construction, base "
            "case, induction step, or combinatorial check) — or cite a confirmed "
            "reference for it. You MAY still abbreviate a genuinely routine step; the "
            "rule is not 'never compress', it is 'never compress a load-bearing "
            "non-routine step into a phrase the verifier cannot check'. "
            "---\n" + gap_fill.rstrip())
    if compile_log:
        parts.append("--- compile_log (the failing pdflatex output) ---\n" + compile_log.rstrip())
    if citation_fixes:
        parts.append(
            "--- citation_fixes (the verifier's per-entry replacement suggestions; "
            "apply against \\bibitem/ledger keys ALREADY present, never invented) ---\n"
            + citation_fixes.rstrip()
        )
    if notes:
        parts.append("--- notes (operator editorial direction for this round) ---\n" + notes.rstrip())
    if not compile_log and not notes and not citation_fixes and not gap_fill:
        parts.append(
            "_(no explicit trigger passed; do a style-audit revision pass per the "
            "role prompt and the operator's editorial annotations already in main.tex)_"
        )
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# public dispatch                                                             #
# --------------------------------------------------------------------------- #

def build_prompt(
    role: str,
    project_dir: Path,
    *,
    headline: Optional[List[str]] = None,
    compile_log: Optional[str] = None,
    notes: Optional[str] = None,
    citation_fixes: Optional[str] = None,
    gap_fill: Optional[str] = None,
    findings: Optional[str] = None,
    paper_id: Optional[str] = None,
    fact_ids: Optional[List[str]] = None,
    instructions: Optional[str] = None,
) -> str:
    """Assemble the full prompt for ``role`` (``writer`` / ``auditor`` /
    ``verifier`` / ``reviser``). Thin dispatch over the per-role helpers; unknown
    roles raise. The writer's structural exemplar is read from the brief (not a
    call arg); the verifier's ``findings`` is the auditor's worklist; the reviser's
    ``citation_fixes`` is the verifier's replacement-suggestion seam. ``paper_id``
    roots every per-paper file at the paper's workspace (default → legacy paths).
    ``fact_ids`` (the main agent's selected subset) + ``instructions`` (its editorial
    direction) are writer-only."""
    if role == "writer":
        return build_writer_prompt(project_dir, headline=headline, paper_id=paper_id,
                                   fact_ids=fact_ids, instructions=instructions)
    if role == "auditor":
        return build_auditor_prompt(project_dir, paper_id=paper_id)
    if role == "verifier":
        return build_verifier_prompt(project_dir, findings=findings, paper_id=paper_id)
    if role == "reviser":
        return build_reviser_prompt(project_dir, compile_log=compile_log,
                                    notes=notes, citation_fixes=citation_fixes,
                                    gap_fill=gap_fill, paper_id=paper_id)
    raise ValueError(f"unknown paper role: {role!r} (expected one of {ROLES})")
