"""Glossary coverage — the one mechanical check kept from proof linting.

Why it stays code: without it the fact graph becomes unreadable — a fact may
use a symbol nobody ever defined. This flags interesting math symbols in a
fact's body that are not defined in (this fact's ``glossary_introduces``) ∪
(any predecessor's) ∪ (the project glossary).

It is a heuristic (regex over math notation), so it is advisory: `fact submit`
should surface undefined symbols and the verifier is the backstop. The text-
hygiene rules (handwave, chart-position refs, …) are NOT here — those are prose
in the worker/verifier prompts.

``glossary_global.json`` (the repo-wide universal-notation glossary) ships as
package data and is loaded via ``importlib.resources`` so it resolves whether the
package is run from a checkout or pip-installed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any, Dict, Iterable, List, Optional, Set

_GLOBAL_RESOURCE = "glossary_global.json"

_GREEK = (
    "alpha beta gamma delta epsilon eta theta iota kappa lambda mu nu xi pi rho "
    "sigma tau phi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega"
).split()

# Tokens that look like math identifiers we expect to be defined: subscripted
# identifiers (S_M, M_q, S_{M_q}), capitalised identifiers with paren/sub, Greek
# parameter names, simple set/interval notation.
_INTERESTING = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z]?(?:_\{[^}]+\}|_[A-Za-z0-9+]+)+(?:\([^)\s]{0,30}\))?"
    r"|[A-Z][A-Z]?(?:\([^)\s]{0,30}\)|\+|>=\d+|<=\d+)"
    r"|" + "|".join(sorted(_GREEK, key=len, reverse=True)) +
    r"|\{[a-zA-Z]\}|\[[a-z],\s*[a-z]\]|\([a-z],\s*[a-z]\)"
    r")"
)

_STOPLIST = frozenset({
    "I", "II", "III", "IV", "V", "VI",
    "OR", "AND", "NOT", "IF", "THEN",
    "QED", "PROOF", "LEMMA", "THEOREM", "CLAIM",
})


def flatten(glossary_obj: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Return {term_or_alias: definition} from a glossary object. Accepts both the
    ``{version, terms: {term: {definition, aliases}}}`` shape (the global glossary)
    and a flat ``{term: definition_str}`` (the per-project / per-fact shape)."""
    out: Dict[str, str] = {}
    if not glossary_obj:
        return out
    terms = glossary_obj["terms"] if isinstance(glossary_obj, dict) and isinstance(
        glossary_obj.get("terms"), dict
    ) else glossary_obj
    for term, entry in (terms or {}).items():
        if isinstance(entry, dict):
            defn = str(entry.get("definition", ""))
            out[str(term)] = defn
            for alias in entry.get("aliases", []) or []:
                out[str(alias)] = defn
        else:
            out[str(term)] = str(entry)
    return out


def _load_global_text() -> Optional[str]:
    """Read the packaged global glossary JSON as text (None if missing)."""
    try:
        return resources.files(__package__).joinpath(_GLOBAL_RESOURCE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, AttributeError, OSError):
        return None


@lru_cache(maxsize=1)
def global_glossary() -> Dict[str, str]:
    """The repo-wide universal-notation glossary, shared by all projects."""
    text = _load_global_text()
    if not text:
        return {}
    try:
        return flatten(json.loads(text))
    except json.JSONDecodeError:
        return {}


def global_terms() -> Set[str]:
    """Symbol names (terms + aliases) that count as defined everywhere."""
    return set(global_glossary())


def undefined_symbols(
    *,
    statement: str,
    proof: str,
    intuition: str = "",
    defined: Iterable[str],
) -> List[str]:
    """Interesting symbols used in the body but not in ``defined`` (the union of
    available glossaries' keys). Returns a de-duplicated, sorted list."""
    defined_set = set(defined)
    found: Dict[str, None] = {}
    for text in (statement, proof, intuition):
        for m in _INTERESTING.finditer(text or ""):
            tok = m.group(1)
            if tok in _STOPLIST or tok in defined_set:
                continue
            # try the base form without a trailing argument list
            stripped = re.sub(r"\([^)]*\)$", "", tok)
            if stripped and stripped in defined_set:
                continue
            found[tok] = None
    return sorted(found)
