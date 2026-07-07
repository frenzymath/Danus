"""Exhaustive offline tests for danus.verify.prechecks — pure functions, no codex.

Covers EVERY precheck function and EVERY rejection branch:
  * is_vacuous_proof: too-few-chars, too-few-words, single vacuous marker, clean pass
  * is_vacuous_statement: too-short, clean pass
  * check_problem_md_citation (P1): each trigger, toggle-off, empty-proof, clean pass
  * check_unproven_conditional_premises (P3): trigger, fact_id pass-through, toggle-off, clean
  * check_vague_gestures (P5): each trigger, toggle-off, clean
  * run_prechecks: vacuous-statement 400, vacuous-proof 400, P1/P3/P5 400 on proof AND
    statement, defensive exception -> treated as no-match, clean pass -> None

Runs standalone (``python -m danus.verify.tests.test_prechecks``) and under pytest.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from danus.verify import prechecks


@contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def _toggles(**attrs):
    """Temporarily override module-level toggles/thresholds read at call time."""
    old = {k: getattr(prechecks, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(prechecks, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(prechecks, k, v)


_GOOD_STATEMENT = "For every integer n, n + 0 equals n."
_GOOD_PROOF = (
    "Zero is the additive identity of the integers, so adding zero to any integer n "
    "leaves the value unchanged. Hence n + 0 = n for every integer n, as required."
)


# --------------------------------------------------------------------------- #
# is_vacuous_proof — every branch                                             #
# --------------------------------------------------------------------------- #

def test_vacuous_proof_too_few_chars():
    vac, reason = prechecks.is_vacuous_proof("QED")
    assert vac is True
    assert "substantive characters" in reason


def test_vacuous_proof_too_few_words():
    # >= MIN_PROOF_CHARS (30) chars but < MIN_PROOF_WORDS (5) words:
    # one very long hyphenated token counts as a single \b\w+\b run per segment.
    proof = "supercalifragilistic aaaaaaaaaaaaaaaaaaaa"  # 2 words, 40 chars
    assert len(prechecks._strip_markdown_noise(proof)) >= prechecks.MIN_PROOF_CHARS
    vac, reason = prechecks.is_vacuous_proof(proof)
    assert vac is True
    assert "substantive words" in reason


def test_vacuous_proof_single_marker():
    # Force thresholds low so a lone vacuous marker reaches the marker branch
    # (line 105) instead of being caught by the char/word gates first.
    with _toggles(MIN_PROOF_CHARS=1, MIN_PROOF_WORDS=1):
        vac, reason = prechecks.is_vacuous_proof("Obviously true.")
        assert vac is True
        assert "vacuous marker" in reason
        assert "obviously true" in reason


def test_vacuous_proof_clean_pass():
    assert prechecks.is_vacuous_proof(_GOOD_PROOF)[0] is False


# --------------------------------------------------------------------------- #
# is_vacuous_statement — every branch                                         #
# --------------------------------------------------------------------------- #

def test_vacuous_statement_too_short():
    vac, reason = prechecks.is_vacuous_statement("x")
    assert vac is True
    assert "substantive characters" in reason


def test_vacuous_statement_clean_pass():
    assert prechecks.is_vacuous_statement(_GOOD_STATEMENT)[0] is False


# --------------------------------------------------------------------------- #
# P1 — check_problem_md_citation                                              #
# --------------------------------------------------------------------------- #

_P1_TRIGGERS = (
    "The claim holds as declared in problem.md, done.",
    "This follows from `problem.md` item 3 building block, so we are done.",
    "It holds by the master reduction package declared in problem.md, hence done.",
    "It holds by the master reduction package declared in the problem statement.",
    "This is standard, as known from the problem prompt, so done.",
    "It follows by the verified reductions listed in problem.md, hence the claim.",
    "The bound holds as stated in data/FOO.md, so we conclude.",
    "We invoke the master reduction package declared in problem.md for closure.",
    "That is the reduction package declared in problem.md, giving the result.",
)


def test_p1_every_trigger():
    for text in _P1_TRIGGERS:
        assert prechecks.check_problem_md_citation(text) is not None, text


def test_p1_toggle_off_returns_none():
    with _toggles(VERIFY_REJECT_PROBLEM_MD_CITATIONS=False):
        assert prechecks.check_problem_md_citation(_P1_TRIGGERS[0]) is None


def test_p1_empty_proof_returns_none():
    assert prechecks.check_problem_md_citation("") is None
    assert prechecks.check_problem_md_citation(None) is None  # type: ignore[arg-type]


def test_p1_clean_pass():
    assert prechecks.check_problem_md_citation(_GOOD_PROOF) is None


# --------------------------------------------------------------------------- #
# P3 — check_unproven_conditional_premises                                    #
# --------------------------------------------------------------------------- #

_P3_TRIGGER = (
    "Assume the verified upstream reductions have narrowed the search space to a "
    "single residual cell before we continue the counting argument."
)


def test_p3_trigger_without_fact_id():
    assert prechecks.check_unproven_conditional_premises(_P3_TRIGGER) is not None


def test_p3_passes_when_fact_id_in_same_paragraph():
    # A 16-hex fact_id in the same paragraph backs the assumption -> `continue`,
    # so the check returns None (pass-through branch, lines 155-156).
    backed = _P3_TRIGGER + " This is backed by fact deadbeefdeadbeef in the graph."
    assert prechecks.check_unproven_conditional_premises(backed) is None


def test_p3_fact_id_in_other_paragraph_still_rejects():
    # fact_id lives in a DIFFERENT paragraph -> does not back the assumption.
    other = (
        _P3_TRIGGER
        + "\n\nSeparately, fact deadbeefdeadbeef is about an unrelated lemma."
    )
    assert prechecks.check_unproven_conditional_premises(other) is not None


def test_p3_post_wq_variants():
    for text in (
        "Assume the verified post-W_q data has been narrowed appropriately here.",
        "Assume the post-W_q reductions have reduced the count to a manageable size.",
        "Suppose the putative residual has been reduced to a single admissible cell.",
    ):
        assert prechecks.check_unproven_conditional_premises(text) is not None, text


def test_p3_toggle_off_returns_none():
    with _toggles(VERIFY_REJECT_UNPROVEN_CONDITIONALS=False):
        assert prechecks.check_unproven_conditional_premises(_P3_TRIGGER) is None


def test_p3_empty_proof_returns_none():
    assert prechecks.check_unproven_conditional_premises("") is None


def test_p3_clean_pass():
    assert prechecks.check_unproven_conditional_premises(_GOOD_PROOF) is None


# --------------------------------------------------------------------------- #
# P5 — check_vague_gestures                                                    #
# --------------------------------------------------------------------------- #

_P5_TRIGGERS = (
    "The estimate follows by some classical argument on the exponential sum.",
    "As it is well known that the bound follows, we conclude the proof.",
    "It follows by an elementary counting argument, hence the claim holds.",
    "The gap closes by some Vinogradov estimate applied to the sum.",
)


def test_p5_every_trigger():
    for text in _P5_TRIGGERS:
        assert prechecks.check_vague_gestures(text) is not None, text


def test_p5_toggle_off_returns_none():
    with _toggles(VERIFY_REJECT_VAGUE_GESTURES=False):
        assert prechecks.check_vague_gestures(_P5_TRIGGERS[0]) is None


def test_p5_empty_proof_returns_none():
    assert prechecks.check_vague_gestures("") is None


def test_p5_clean_pass():
    assert prechecks.check_vague_gestures(_GOOD_PROOF) is None


# --------------------------------------------------------------------------- #
# run_prechecks — the orchestrator, every rejection path                      #
# --------------------------------------------------------------------------- #

def test_run_prechecks_clean_pass():
    assert prechecks.run_prechecks(_GOOD_STATEMENT, _GOOD_PROOF) is None


def test_run_prechecks_vacuous_statement_400():
    out = prechecks.run_prechecks("x", _GOOD_PROOF)
    assert out is not None and out[0] == 400
    assert "vacuous statement" in out[1]


def test_run_prechecks_vacuous_proof_400():
    out = prechecks.run_prechecks(_GOOD_STATEMENT, "QED")
    assert out is not None and out[0] == 400
    assert "vacuous proof" in out[1]


def test_run_prechecks_p1_on_proof_400():
    out = prechecks.run_prechecks(_GOOD_STATEMENT, _P1_TRIGGERS[0])
    assert out is not None and out[0] == 400
    assert "[P1 on proof]" in out[1]


def test_run_prechecks_p5_on_statement_400():
    # A bad pattern hiding in the STATEMENT (not the proof) is still caught,
    # exercising the ("statement", statement) source-label branch.
    bad_statement = (
        "Claim: as it is well known that the sum is bounded, the theorem holds."
    )
    out = prechecks.run_prechecks(bad_statement, _GOOD_PROOF)
    assert out is not None and out[0] == 400
    assert "[P5 on statement]" in out[1]


def test_run_prechecks_p3_400():
    out = prechecks.run_prechecks(_GOOD_STATEMENT, _P3_TRIGGER)
    assert out is not None and out[0] == 400
    assert "[P3 on proof]" in out[1]


def test_run_prechecks_defensive_exception_is_no_match(monkeypatch):
    # A check that raises must be treated as "no match" (never a 500). Force P1 to
    # blow up and confirm run_prechecks swallows it and still passes clean input.
    def boom(_proof):
        raise RuntimeError("pathological regex / bug")

    monkeypatch.setattr(prechecks, "check_problem_md_citation", boom)
    assert prechecks.run_prechecks(_GOOD_STATEMENT, _GOOD_PROOF) is None


def main() -> None:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    # monkeypatch-dependent test is pytest-only; run the rest standalone.
    import inspect

    for fn in fns:
        params = inspect.signature(fn).parameters
        if params:
            print(f"  [skip standalone] {fn.__name__} (needs pytest fixture)")
            continue
        fn()
        print(f"  [ok] {fn.__name__}")
    print("ALL PRECHECKS TESTS PASSED")


if __name__ == "__main__":
    main()
