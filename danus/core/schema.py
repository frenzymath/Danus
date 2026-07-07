"""Schemas + content-addressed fact id for the three core data structures.

Kept minimal on purpose: code only models the *fixed* parts of the data
structures (the fact node and the fact id). Behavior — when to publish, verify,
promote — is prose (prompts/skills), not code.

The glossary (``glossary_introduces``) is kept: it is what makes a fact readable
and composable (every symbol has a definition somewhere). See ``DATA_MODEL.md``
§3 and ``glossary.py``. ``compute_fact_id`` is the Danus scheme, including the
glossary term.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List

# --------------------------------------------------------------------------- #
# global memory kinds (the strong categorization) + statuses                  #
# --------------------------------------------------------------------------- #

# kind -> default `verifiable` (objectively checkable vs. a judgment).
GLOBAL_KINDS: Dict[str, bool] = {
    "conclusion": True,
    "example": True,
    "counterexample": True,
    "proof_attempt": True,
    "plan": False,
    "dead_end": False,
    "direction": False,
    "obstacle": False,
    "master_guidance": False,  # main agent, via GPT-5.5-pro (DATA_MODEL.md §2.3)
    "verification": False,     # trace of a fact_submit verification outcome (logged by fact_submit)
    "elaboration": False,      # main agent's periodic high-signal progress synthesis (DATA_MODEL.md §2.4)
}

# A global-memory entry's lifecycle. Set/advanced by the agent; the store just
# records it (no enforcement machinery).
STATUSES = (
    "unverified", "verifying", "verified", "refuted",  # verifiable entries
    "open", "supported", "challenged",                  # judgment entries
)


# --------------------------------------------------------------------------- #
# fact node (the only structured schema we keep)                              #
# --------------------------------------------------------------------------- #

# Canonical key order for a structured external reference (a published result the
# proof cites). Extra keys are preserved but sorted after these. Kept loose on
# purpose — bibliographic data is filled by the worker and corrected by the paper
# pipeline's reference auditor, not policed here.
EXTERNAL_REF_KEYS = ("key", "authors", "title", "arxiv", "year", "venue", "doi", "cited_for")


def clean_external_refs(refs: object) -> List[Dict[str, object]]:
    """Normalize an external-refs payload to a list of plain JSON-safe dicts with a
    stable key order. Drops non-dict entries; never raises (advisory data)."""
    if not refs:
        return []
    out: List[Dict[str, object]] = []
    for r in refs:  # type: ignore[union-attr]
        if not isinstance(r, dict):
            continue
        ordered = {k: r[k] for k in EXTERNAL_REF_KEYS if k in r}
        for k in sorted(r):  # preserve any extra keys, deterministically
            if k not in ordered:
                ordered[k] = r[k]
        out.append(ordered)
    return out


@dataclass
class Fact:
    """A verified fact = one node in the fact graph. Frontmatter (fact_id /
    problem_id / author / predecessors / glossary_introduces / external_refs) +
    the markdown body (statement / proof / optional intuition)."""

    fact_id: str
    problem_id: str
    author: str
    predecessors: List[str]                    # bare-hex fact ids (the DAG)
    statement: str
    proof: str
    glossary_introduces: Dict[str, str] = field(default_factory=dict)  # symbol -> definition
    intuition: str = ""
    # Structured bibliography of external (published) results the proof cites.
    # Mutable metadata — NOT part of the content-addressed fact_id (see
    # compute_fact_id): the reference auditor corrects these post-hoc, so binding
    # them into the id would break the DAG on every audit. The citation *keys* used
    # in the proof text are already hashed (they live in `proof`).
    external_refs: List[Dict[str, object]] = field(default_factory=list)


def _normalize(text: str) -> str:
    """Whitespace-stable canonical form for content hashing (cosmetic edits do
    not perturb the fact_id)."""
    return re.sub(r"\s+", " ", text or "").strip()


def compute_fact_id(
    *,
    problem_id: str,
    predecessors: List[str],
    glossary_introduces: Dict[str, str],
    statement: str,
    proof: str,
) -> str:
    """Deterministic 16-hex SHA-256 of the canonical content (the Danus scheme).
    Same content -> same id -> natural dedup.

    Note: ``external_refs`` is deliberately excluded — it is mutable bibliographic
    metadata the reference auditor corrects after the fact is verified; hashing it
    would change the id (and break the DAG) on every audit, and would also perturb
    the ids of all pre-existing facts. The cited keys themselves are already in
    ``proof``, which is hashed."""
    body = {
        "problem_id": problem_id,
        "predecessors": sorted(predecessors),
        "glossary_introduces": dict(
            sorted((str(k), str(v)) for k, v in glossary_introduces.items())
        ),
        "statement": _normalize(statement),
        "proof": _normalize(proof),
    }
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()[:16]
