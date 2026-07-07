"""Deterministic pre-checks for the verify service — run BEFORE any codex call.

Two layers, both purely ADDITIVE (they can only REJECT more, never ACCEPT more),
each env-toggleable:

  1. Vacuousness — refuse near-empty / one-word ("QED", "obvious") inputs so the
     verifier can never be tricked into "passing" nothing.
  2. Hard prohibitions P1 / P3 / P5 — regex rejections of specific bad proof
     shapes (citing the problem statement as a math source; an unproven
     conditional premise with no backing fact_id; a vague gesture at a
     "well-known"/classical result with no citation).

NOTE: the P1/P3/P5 patterns are tuned to specific proof-failure shapes
(e.g. the "master reduction package", "post-W_q"). They are safe (additive) but
domain-specific; keep, generalize, or disable them to fit your domain.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

# --------------------------------------------------------------------------- #
# vacuousness thresholds (env-configurable)                                   #
# --------------------------------------------------------------------------- #
MIN_STATEMENT_CHARS = int(os.getenv("VERIFY_MIN_STATEMENT_CHARS", "10"))
MIN_PROOF_CHARS = int(os.getenv("VERIFY_MIN_PROOF_CHARS", "30"))
MIN_PROOF_WORDS = int(os.getenv("VERIFY_MIN_PROOF_WORDS", "5"))

_VACUOUS_PROOF_MARKERS = (
    "todo", "fixme", "tbd", "to be done", "see above", "see below", "obvious",
    "obviously true", "trivial", "trivially true", "left as exercise",
    "left to the reader", "exercise for the reader", "by inspection",
    "by definition", "clear", "clearly", "qed",
)

# --------------------------------------------------------------------------- #
# hard-prohibition toggles (default ON; set to "0" to disable)                #
# --------------------------------------------------------------------------- #
VERIFY_REJECT_PROBLEM_MD_CITATIONS = os.getenv("VERIFY_REJECT_PROBLEM_MD_CITATIONS", "1") == "1"
VERIFY_REJECT_UNPROVEN_CONDITIONALS = os.getenv("VERIFY_REJECT_UNPROVEN_CONDITIONALS", "1") == "1"
VERIFY_REJECT_VAGUE_GESTURES = os.getenv("VERIFY_REJECT_VAGUE_GESTURES", "1") == "1"

# P1: problem.md / data/<NAME>.md cited as a substantive math source.
_PROBLEM_MD_CITATION_PATTERNS = (
    re.compile(r"\bas\s+declared\s+in[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md\b", re.IGNORECASE),
    re.compile(r"\bfrom[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md[\s`'\"]+(?:item|section|building\s+block|reduction)\b", re.IGNORECASE),
    re.compile(r"\bby\s+the\s+master\s+reduction\s+package\s+declared\s+in[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md\b", re.IGNORECASE),
    re.compile(r"\bby\s+the\s+master\s+reduction\s+package\s+declared\s+in\s+the\s+problem\s+statement\b", re.IGNORECASE),
    re.compile(r"\bas\s+known\s+from\s+(?:the\s+problem\s+(?:prompt|statement)|problem\.md|data/[A-Za-z0-9_]+\.md)\b", re.IGNORECASE),
    re.compile(r"\bby\s+the\s+verified\s+(?:reductions?|building\s+blocks?)\s+listed\s+in[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md\b", re.IGNORECASE),
    re.compile(r"\bas\s+stated\s+in[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:master\s+)?reduction\s+package\s+(?:declared|stated)\s+in[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md\b", re.IGNORECASE),
    re.compile(r"\b(?:this|that|it)\s+is\s+the\s+(?:master\s+)?reduction\s+package\s+declared\s+in[\s`'\"]+(?:problem|data/[A-Za-z0-9_]+)\.md\b", re.IGNORECASE),
)

# P3: unproven conditional premises, bad UNLESS a 16-hex fact_id backs them in the
# same paragraph.
_CONDITIONAL_PREMISE_PATTERNS = (
    re.compile(r"\bassume\s+(?:that\s+)?the\s+verified\s+[^.]{0,100}?\breductions?\s+have\s+(?:reduced|narrowed|placed|brought|moved|driven)", re.IGNORECASE),
    re.compile(r"\bassume\s+(?:that\s+)?the\s+verified\s+post-W_q\b", re.IGNORECASE),
    re.compile(r"\bassume\s+(?:that\s+)?the\s+post-W_q[^.]{0,100}?\breductions?\s+have\s+", re.IGNORECASE),
    re.compile(r"\bsuppose\s+(?:that\s+)?the\s+(?:no-hit\s+)?(?:putative\s+)?(?:residual|survivor|cell|data)\s+has\s+been\s+(?:reduced|narrowed|placed|moved|brought|driven)", re.IGNORECASE),
)

_FACT_ID_PATTERN = re.compile(r"\b[0-9a-f]{16}\b")

# P5: vague gestures at classical/well-known results without a specific citation.
_VAGUE_GESTURE_PATTERNS = (
    re.compile(r"\bby\s+some\s+(?:Beatty|Dirichlet|Diophantine|Vinogradov|Weyl|Erd[oö]s[‐‑–—-]Tur[aá]n|classical|well-known)\s+(?:argument|theorem|inequality|estimate)\b", re.IGNORECASE),
    re.compile(r"\b(?:as|it)\s+is\s+well\s+known\s+(?:that|in\s+the\s+literature)\b", re.IGNORECASE),
    re.compile(r"\bby\s+(?:an?\s+)?(?:obvious|elementary|straightforward|standard)\s+(?:density|Diophantine|integer|approximation|estimation|counting|equidistribution)\s+(?:argument|theorem|principle)\b", re.IGNORECASE),
)


def _strip_markdown_noise(text: str) -> str:
    """Remove code fences / inline code / quote & hr / header markers and collapse
    whitespace, so markdown wrappers can't make a vacuous proof look substantive."""
    no_fences = re.sub(r"```[\s\S]*?```", "", text)
    no_inline_code = re.sub(r"`[^`\n]*`", "", no_fences)
    no_quotes = re.sub(r"^\s*>\s?", "", no_inline_code, flags=re.MULTILINE)
    no_hr = re.sub(r"^\s*[-*_]{3,}\s*$", "", no_quotes, flags=re.MULTILINE)
    no_headers = re.sub(r"^\s*#+\s*", "", no_hr, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", no_headers).strip()


def is_vacuous_proof(proof: str) -> Tuple[bool, str]:
    """(is_vacuous, reason). Conservative: only flags proofs that are short AND
    reduce to a single vacuous marker. A real one-line theorem-citing proof passes."""
    cleaned = _strip_markdown_noise(proof)
    if len(cleaned) < MIN_PROOF_CHARS:
        return True, (
            f"proof has only {len(cleaned)} substantive characters after stripping "
            f"markdown noise (minimum {MIN_PROOF_CHARS}). A vacuous or near-empty "
            "proof cannot be passed by the verifier."
        )
    word_count = len(re.findall(r"\b\w+\b", cleaned))
    if word_count < MIN_PROOF_WORDS:
        return True, f"proof has only {word_count} substantive words (minimum {MIN_PROOF_WORDS})."
    stripped_lowered = re.sub(r"[^\w\s]", "", cleaned.lower()).strip()
    for marker in _VACUOUS_PROOF_MARKERS:
        if stripped_lowered == marker:
            return True, (
                f'proof body reduces to the vacuous marker "{marker}" after '
                "stripping punctuation and markdown noise."
            )
    return False, ""


def is_vacuous_statement(statement: str) -> Tuple[bool, str]:
    """(is_vacuous, reason). Only refuses statements too short to be real."""
    cleaned = _strip_markdown_noise(statement)
    if len(cleaned) < MIN_STATEMENT_CHARS:
        return True, (
            f"statement has only {len(cleaned)} substantive characters after "
            f"stripping markdown noise (minimum {MIN_STATEMENT_CHARS}). Refusing to "
            "verify against an essentially empty statement."
        )
    return False, ""


def check_problem_md_citation(proof: str) -> Optional[str]:
    """P1: reject proofs citing problem.md / data/<NAME>.md as a math source."""
    if not VERIFY_REJECT_PROBLEM_MD_CITATIONS or not isinstance(proof, str) or not proof:
        return None
    for pat in _PROBLEM_MD_CITATION_PATTERNS:
        m = pat.search(proof)
        if m:
            return (
                f"Hard Prohibition P1: the proof cites problem.md / data/<NAME>.md as a "
                f"substantive math source. Matched phrase: {m.group(0)!r}. Replace with a "
                f"specific verified fact_id from the fact graph; problem.md is the target "
                f"description, not a source of premises. Override: set "
                f"VERIFY_REJECT_PROBLEM_MD_CITATIONS=0."
            )
    return None


def check_unproven_conditional_premises(proof: str) -> Optional[str]:
    """P3: reject "Assume the verified ... reductions have narrowed ..." UNLESS a
    16-hex fact_id appears in the same paragraph backing it."""
    if not VERIFY_REJECT_UNPROVEN_CONDITIONALS or not isinstance(proof, str) or not proof:
        return None
    for pat in _CONDITIONAL_PREMISE_PATTERNS:
        for m in pat.finditer(proof):
            start, end = m.start(), m.end()
            para_start = proof.rfind("\n\n", 0, start)
            if para_start < 0:
                para_start = 0
            para_end = proof.find("\n\n", end)
            if para_end < 0:
                para_end = len(proof)
            if _FACT_ID_PATTERN.search(proof[para_start:para_end]):
                continue
            return (
                f"Hard Prohibition P3: the proof contains a conditional-premise phrase "
                f"({m.group(0)!r}) but no specific verified fact_id is cited in the same "
                f"paragraph proving the assumed narrowing. Either replace the assumption "
                f"with a specific citation or cite a backing fact_id in the same paragraph. "
                f"Override: set VERIFY_REJECT_UNPROVEN_CONDITIONALS=0."
            )
    return None


def check_vague_gestures(proof: str) -> Optional[str]:
    """P5: reject a vague gesture at a 'well-known'/classical result with no citation."""
    if not VERIFY_REJECT_VAGUE_GESTURES or not isinstance(proof, str) or not proof:
        return None
    for pat in _VAGUE_GESTURE_PATTERNS:
        m = pat.search(proof)
        if m:
            return (
                f"Hard Prohibition P5: the proof gestures at a 'well-known'/classical "
                f"result without a specific citation. Matched phrase: {m.group(0)!r}. "
                f"Replace with a specific verified fact_id or an external paper citation "
                f"(paper_id / theorem_id / arXiv id). Override: set "
                f"VERIFY_REJECT_VAGUE_GESTURES=0."
            )
    return None


def run_prechecks(statement: str, proof: str) -> Optional[Tuple[int, str]]:
    """Run every pre-check. Returns ``(http_status, detail)`` for the first
    rejection, or ``None`` if all pass. The vacuous checks are 400s; the P1/P3/P5
    hard prohibitions are 400s run on BOTH the proof and the statement (a bad
    pattern can hide in a lemma's hypothesis). A pathological regex is treated as
    'no match' (defensive) so a check can never turn into a 500."""
    vac, reason = is_vacuous_statement(statement)
    if vac:
        return 400, f"vacuous statement: {reason}"
    vac, reason = is_vacuous_proof(proof)
    if vac:
        return 400, f"vacuous proof: {reason}"

    for check_fn, name in (
        (check_problem_md_citation, "P1"),
        (check_unproven_conditional_premises, "P3"),
        (check_vague_gestures, "P5"),
    ):
        for source_label, source_text in (("proof", proof), ("statement", statement)):
            try:
                reason = check_fn(source_text)
            except Exception:  # noqa: BLE001 - defensive: a check must never 500
                reason = None
            if reason:
                return 400, f"[{name} on {source_label}] {reason}"
    return None
