"""Deterministic prompt assembler for the human-summary report writer.

Pure functions: read the fixed writer prompt, the project's verbatim
``PROBLEM.md``, and a **scrubbed** bundle of the project's verified facts, then
concatenate them into one prompt string with explicit section delimiters. No
codex, no network, no writes — everything here is testable in isolation.

The load-bearing property this module enforces (the reason it exists):

  The report writer runs ISOLATED and must never see pipeline identifiers or
  machinery. So the fact bundle embeds, for each selected fact, ONLY its body
  sections (``## statement`` / ``## proof`` / ``## intuition``). The entire YAML
  frontmatter — ``fact_id`` / ``author`` / ``problem_id`` / ``predecessors`` /
  ``glossary_introduces`` / ``external_refs`` — is STRIPPED, and no fact id or
  slug is emitted anywhere. The writer works from mathematics, nothing else.

Every verified fact is emitted in topological order (a fact always follows every
fact it depends on); no fact is dropped. Dependency depth (longest predecessor
chain) and in-degree (how many facts name it as a predecessor) only break ties
within a topological level, so the load-bearing results lead where the order is
otherwise free.

The writer prompt lives in the operator-editable skill dir, located at CALL time
via ``DANUS_HUMAN_SUMMARY_SKILL_DIR`` (default
``<repo_root>/agents/skills/human-summary``); never read at import time. Every
required file is read verbatim, in full, and a missing file fails loudly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from danus.authoring.common import body_sections, read_fixed, read_project, section
from danus.core import FactGraph

# danus/human_summary/assemble.py -> repo root is two parents up; the default skill
# dir is the shipped human-summary codex-facing assets.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SKILL_DIR = _REPO_ROOT / "agents" / "skills" / "human-summary"

WRITER_PROMPT_REL = "REPORT_WRITER_PROMPT.md"


# --------------------------------------------------------------------------- #
# config resolution (env read at CALL time — testable / reconfigurable)       #
# --------------------------------------------------------------------------- #

def skill_dir() -> Path:
    """The operator-editable skill dir holding the fixed writer prompt.
    ``DANUS_HUMAN_SUMMARY_SKILL_DIR`` (env) wins; default is the shipped skill."""
    override = os.environ.get("DANUS_HUMAN_SUMMARY_SKILL_DIR", "")
    return Path(override) if override else _DEFAULT_SKILL_DIR


# --------------------------------------------------------------------------- #
# section helpers                                                             #
# --------------------------------------------------------------------------- #

def _read_fixed(rel: str) -> str:
    """Read a fixed skill file **verbatim, in full** from the human-summary skill
    dir (thin wrapper over ``authoring.common.read_fixed`` binding ``skill_dir()``)."""
    return read_fixed(skill_dir(), rel)


def _read_project(project_dir: Path, rel: str) -> str:
    """Read a required per-project file verbatim; fail loudly if missing."""
    return read_project(project_dir, rel)


# --------------------------------------------------------------------------- #
# scrubbed fact bundle                                                         #
# --------------------------------------------------------------------------- #

def _body_sections(raw: str) -> str:
    """The fact's body with the YAML frontmatter STRIPPED — the shared scrub
    (``authoring.common.body_sections``): no ``fact_id`` / ``author`` /
    ``problem_id`` / ``predecessors`` / ``glossary_introduces`` / ``external_refs``
    reaches the writer. The body math is preserved verbatim — never summarize a
    proof."""
    return body_sections(raw)


def _depth(fg: FactGraph, fid: str, cache: Dict[str, int]) -> int:
    """Longest predecessor chain ending at ``fid`` (leaves = 0). Memoized;
    tolerant of cycles (should not occur in a verified DAG) via a visiting set."""
    if fid in cache:
        return cache[fid]
    cache[fid] = 0  # break cycles: treat a back-edge as depth 0
    preds = fg.predecessors(fid)
    d = 0 if not preds else 1 + max(_depth(fg, p, cache) for p in preds)
    cache[fid] = d
    return d


def _in_degree(fg: FactGraph, ids: List[str]) -> Dict[str, int]:
    """How many facts (among ``ids``) name each fact as a direct predecessor."""
    deg: Dict[str, int] = {fid: 0 for fid in ids}
    for fid in ids:
        for p in fg.predecessors(fid):
            if p in deg:
                deg[p] += 1
    return deg


def _ordered_load_bearing(fg: FactGraph) -> List[str]:
    """Every verified fact, topologically ordered (predecessors before the facts
    that depend on them). Ranking by dependency depth + in-degree decides the
    tie-break within a topological level so the load-bearing spine reads in a
    natural order; no fact is dropped (each is verified and may be needed for a
    self-contained statement)."""
    ids = fg.list()
    if not ids:
        return []
    depth_cache: Dict[str, int] = {}
    depth = {fid: _depth(fg, fid, depth_cache) for fid in ids}
    indeg = _in_degree(fg, ids)
    # Kahn-style stable topological sort; within a ready set, prefer higher
    # (depth, in-degree) so the load-bearing results lead, ties broken by id.
    id_set = set(ids)
    preds_in = {fid: [p for p in fg.predecessors(fid) if p in id_set] for fid in ids}
    placed: set = set()
    ordered: List[str] = []
    remaining = set(ids)
    while remaining:
        ready = [fid for fid in remaining if all(p in placed for p in preds_in[fid])]
        if not ready:  # a cycle (should not happen) — append deterministically
            ready = sorted(remaining)
        ready.sort(key=lambda f: (-depth[f], -indeg[f], f))
        chosen = ready[0]
        ordered.append(chosen)
        placed.add(chosen)
        remaining.discard(chosen)
    return ordered


def fact_bundle(project_dir: Path) -> str:
    """The scrubbed fact bundle: each load-bearing fact's body sections
    (statement / proof / intuition), id-free, in dependency order. No frontmatter,
    no fact id, no slug — nothing but the mathematics."""
    fg = FactGraph(Path(project_dir))
    ids = _ordered_load_bearing(fg)
    if not ids:
        return "_(no verified results are available for this project yet)_\n"
    blocks: List[str] = []
    for n, fid in enumerate(ids, start=1):
        raw = fg.get_raw(fid) or ""
        blocks.append(f"--- Result {n} ---\n{_body_sections(raw)}")
    return "\n".join(blocks)


# --------------------------------------------------------------------------- #
# public assembler                                                            #
# --------------------------------------------------------------------------- #

def build_prompt(project_dir: Path, language: str = "English") -> str:
    """Assemble the isolated report writer's full prompt: the fixed writer prompt
    (verbatim) + the project's verbatim ``PROBLEM.md`` + the scrubbed, id-free
    fact bundle. The large bytes are assembled HERE, never in the main agent's
    context; the writer codex sees only mathematics, no pipeline identifiers.

    ``language`` names the narrative language for the report (the register rule:
    prose in this language, ALL standard math terminology in English). It is a
    plain report parameter — only the language *name* crosses into the prompt, not
    ``OPERATOR.md`` or any machinery."""
    project_dir = Path(project_dir)
    parts = [
        "You are the REPORT WRITER. Everything you need is embedded below; you have "
        "no filesystem to read and no tools. Write the human-facing progress report "
        "per the rules, from ONLY the problem statement and the scrubbed results "
        "below. You have no identifiers, no author names, and no system vocabulary "
        "— never invent or mention any.",
        f"\n\nReport language: {language}. Write the narrative in {language}; keep "
        "ALL standard mathematical terminology in English regardless (never a "
        "native-language calque for an established term) — see the register rule in "
        "the writer prompt. The mathematics is identical in any language.",
        section(WRITER_PROMPT_REL, _read_fixed(WRITER_PROMPT_REL)),
        section("PROBLEM.md (verbatim goal)", _read_project(project_dir, "PROBLEM.md")),
        section("VERIFIED_RESULTS (scrubbed, id-free)", fact_bundle(project_dir)),
    ]
    return "".join(parts)
