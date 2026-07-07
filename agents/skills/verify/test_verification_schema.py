"""Schema guard for the verifier's final JSON contract (skill-3 output).

This pins the shape the `synthesize-verification-report` skill must emit and the
verify service returns verbatim as the `/verify` HTTP response:

    {
      "verification_report": {"summary", "critical_errors": [...], "gaps": [...]},
      "verdict": "correct" | "wrong",
      "repair_hints": ""            # non-empty iff verdict == "wrong"
    }

It complements the verify service's fake-codex sanity harness; it is a cheap,
LLM-independent guard that the contract stays shaped. It asserts only the
structural contract, not any mathematical judgement.
"""

import pytest


def validate_verification_output(payload):
    """Return the payload if it satisfies the final JSON contract, else raise.

    Rules (the strict verdict rule, in schema form):
      - `verdict` is exactly "correct" or "wrong".
      - every entry of `critical_errors` / `gaps` has both `location` and `issue`.
      - `verdict == "correct"` iff both lists are empty.
      - `repair_hints` is non-empty iff `verdict == "wrong"` ("" when "correct").
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    report = payload.get("verification_report")
    if not isinstance(report, dict):
        raise ValueError("verification_report must be a dict")
    if not isinstance(report.get("summary"), str):
        raise ValueError("verification_report.summary must be a string")

    for key in ("critical_errors", "gaps"):
        findings = report.get(key)
        if not isinstance(findings, list):
            raise ValueError(f"verification_report.{key} must be a list")
        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError(f"each {key} entry must be a dict")
            if not finding.get("location") or not isinstance(finding["location"], str):
                raise ValueError(f"each {key} entry needs a non-empty string location")
            if not finding.get("issue") or not isinstance(finding["issue"], str):
                raise ValueError(f"each {key} entry needs a non-empty string issue")

    verdict = payload.get("verdict")
    if verdict not in ("correct", "wrong"):
        raise ValueError('verdict must be "correct" or "wrong"')

    repair_hints = payload.get("repair_hints")
    if not isinstance(repair_hints, str):
        raise ValueError("repair_hints must be a string")

    clean = not report["critical_errors"] and not report["gaps"]
    # Strict verdict rule: correct iff zero critical_errors AND zero gaps.
    if clean and verdict != "correct":
        raise ValueError("no findings but verdict is not correct")
    if not clean and verdict != "wrong":
        raise ValueError("findings present but verdict is not wrong")

    # repair_hints non-empty iff wrong.
    if verdict == "correct" and repair_hints != "":
        raise ValueError('verdict "correct" requires empty repair_hints')
    if verdict == "wrong" and not repair_hints.strip():
        raise ValueError('verdict "wrong" requires non-empty repair_hints')

    return payload


def test_accept_clean_proof():
    validate_verification_output(
        {
            "verification_report": {"summary": "ok", "critical_errors": [], "gaps": []},
            "verdict": "correct",
            "repair_hints": "",
        }
    )


def test_reject_on_critical_error():
    validate_verification_output(
        {
            "verification_report": {
                "summary": "bad implication",
                "critical_errors": [{"location": "Lemma 3", "issue": "A does not imply B."}],
                "gaps": [],
            },
            "verdict": "wrong",
            "repair_hints": "Prove A => B or drop the step.",
        }
    )


def test_reject_on_gap_alone():
    # Gaps alone force "wrong" — never relax to "no critical errors only".
    validate_verification_output(
        {
            "verification_report": {
                "summary": "missing bound",
                "critical_errors": [],
                "gaps": [{"location": "proof paragraph 2", "issue": "boundedness unproved."}],
            },
            "verdict": "wrong",
            "repair_hints": "Add the boundedness argument.",
        }
    )


@pytest.mark.parametrize(
    "payload",
    [
        # correct verdict with a finding present
        {
            "verification_report": {
                "summary": "x",
                "critical_errors": [{"location": "L1", "issue": "bad"}],
                "gaps": [],
            },
            "verdict": "correct",
            "repair_hints": "",
        },
        # wrong verdict but no findings
        {
            "verification_report": {"summary": "x", "critical_errors": [], "gaps": []},
            "verdict": "wrong",
            "repair_hints": "something",
        },
        # correct verdict with non-empty repair_hints
        {
            "verification_report": {"summary": "x", "critical_errors": [], "gaps": []},
            "verdict": "correct",
            "repair_hints": "leftover",
        },
        # wrong verdict with empty repair_hints
        {
            "verification_report": {
                "summary": "x",
                "critical_errors": [{"location": "L1", "issue": "bad"}],
                "gaps": [],
            },
            "verdict": "wrong",
            "repair_hints": "   ",
        },
        # unknown verdict value
        {
            "verification_report": {"summary": "x", "critical_errors": [], "gaps": []},
            "verdict": "maybe",
            "repair_hints": "",
        },
        # finding missing issue
        {
            "verification_report": {
                "summary": "x",
                "critical_errors": [{"location": "L1"}],
                "gaps": [],
            },
            "verdict": "wrong",
            "repair_hints": "fix it",
        },
    ],
)
def test_contract_violations_raise(payload):
    with pytest.raises(ValueError):
        validate_verification_output(payload)
