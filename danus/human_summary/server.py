"""human-summary — the human-summary skill's MCP service (role-gated: main only).

Wraps the isolated report writer behind a hard-coded MCP tool so the main agent
gets a clean ``report.md`` **without ever authoring the prose itself and without
ever reading the fact files**. The large bytes (the writer prompt + the scrubbed
fact bundle) are assembled inside the tool (``assemble.py``) and never pass
through the main agent's context, and the writer's codex runs isolated by
construction (``danus.authoring.driver`` — empty cwd + fully-embedded prompt).

The structural fix this service is: the report author is an ISOLATED codex fed a
scrubbed, id-free bundle — it is impossible for it to receive ``fact_id`` /
``author`` / ``predecessors`` / other frontmatter or swarm/orchestration
vocabulary, because ``assemble.py`` strips all of it. A regex LEAK CHECK on the
codex output is the backstop: a report that still contains a hex id, an ``author:``
line, a ``fact_`` slug, or machinery terms is reported ``status != ok`` and is NOT
kept.

Tool returns are **small and honest**: paths + status + flags, never the full
report. ``status`` is ``ok`` only on a zero exit AND non-empty output AND zero leak
findings; a nonzero exit, empty stdout, timeout, or any leak is not ``ok``.

Config resolution (env read at CALL time):
  DANUS_AGENTS_ROOT / DANUS_PROJECT_DIR         which project to operate on
  DANUS_HUMAN_SUMMARY_SKILL_DIR                 the writer prompt (see assemble.py)
  DANUS_CODEX_BIN                               codex binary
  DANUS_HUMAN_SUMMARY_MODEL / DANUS_HUMAN_SUMMARY_EFFORT   per-service codex
                      overrides; fall back to neutral DANUS_CODEX_MODEL / DANUS_CODEX_EFFORT
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from danus.authoring import driver
from danus.authoring.common import classify_outcome, resolve_project
from danus.authoring.common import leak_findings as _scan_leaks

from . import assemble

_REPO_ROOT = Path(__file__).resolve().parents[2]

# LEAK CHECK — patterns that must NEVER appear in a human-facing report. Each is a
# tell that pipeline metadata or machinery vocabulary survived into the output.
# The set forbids 'predecessors' / 'verifier' / 'worker' / 'global memory' — a
# reader-facing report has no legitimate use for that swarm vocabulary.
_LEAK_PATTERNS = [
    (r"\b[0-9a-f]{16}\b", "16-hex id (fact_id / hash prefix)"),
    (r"(?im)^\s*author:", "'author:' frontmatter line"),
    (r"(?i)\bpredecessors\b", "'predecessors' (frontmatter / DAG vocabulary)"),
    (r"(?i)\bfact_[a-z0-9_]+", "'fact_' slug / identifier"),
    (r"(?i)\bmaster_guidance\b", "'master_guidance' (strategy-consult machinery)"),
    (r"(?i)\bfact_submit\b", "'fact_submit' (pipeline verb)"),
    (r"(?i)\bverifier\b", "'verifier' (system machinery)"),
    (r"(?i)\bworker\b", "'worker' (swarm machinery)"),
    (r"(?i)\bglobal memory\b", "'global memory' (system store)"),
]


def _model() -> str:
    """Per-service model override, else the neutral default:
    DANUS_HUMAN_SUMMARY_MODEL -> DANUS_CODEX_MODEL -> the driver's built-in default."""
    return os.environ.get("DANUS_HUMAN_SUMMARY_MODEL") or driver.default_model()


def _effort() -> str:
    """Per-service effort override, else the neutral default:
    DANUS_HUMAN_SUMMARY_EFFORT -> DANUS_CODEX_EFFORT -> the driver's built-in default."""
    return os.environ.get("DANUS_HUMAN_SUMMARY_EFFORT") or driver.default_effort()


def _drive(prompt: str) -> Dict[str, Any]:
    """Run the codex driver once and classify the outcome honestly (see
    ``authoring.common.classify_outcome``: ``ok`` needs a zero exit AND non-empty
    stdout; a nonzero exit, timeout, missing binary, or empty output is not
    ``ok``)."""
    try:
        cp: Any = driver.run_codex(prompt, model=_model(), effort=_effort())
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        cp = e
    return classify_outcome(cp, artifact_noun="report")


def leak_findings(report: str) -> List[str]:
    """Every leak-pattern hit in ``report`` (deduplicated, human-readable). Empty
    list ⇒ the report is clean of ids and machinery vocabulary. Thin wrapper over
    ``authoring.common.leak_findings`` binding this service's stricter pattern set."""
    return _scan_leaks(report, _LEAK_PATTERNS)


def _operator_language() -> Optional[str]:
    """The operator's narrative language from repo-root ``OPERATOR.md`` (the
    ``**Language:**`` field), or ``None`` if it is still the blank template. Only
    the language NAME crosses into the report prompt — never OPERATOR.md itself,
    which is main-agent machinery. Read at call time."""
    path = _REPO_ROOT / "OPERATOR.md"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if "**Language:**" in line:
            val = line.split("**Language:**", 1)[1].strip()
            # the blank-template placeholder is wrapped in "_( … )_"
            return val if val and not val.startswith("_(") else None
    return None


# --------------------------------------------------------------------------- #
# tool                                                                         #
# --------------------------------------------------------------------------- #

def summary_write(project: Optional[str] = None, language: Optional[str] = None) -> Dict[str, Any]:
    """Write a clean, human-facing progress report for a project to
    ``<project>/report/report.md``. Assembles the report writer's prompt (the
    verbatim problem statement + a SCRUBBED, id-free bundle of the project's
    verified results — no fact ids, no author names, no machinery — all embedded,
    nothing enters your context), drives an ISOLATED local codex, writes its
    stdout, then runs a LEAK CHECK on the output.

    ``language`` sets the report's narrative language (math terminology stays
    English regardless). If omitted, it is resolved from the operator's
    ``OPERATOR.md`` ``**Language:**`` field, else defaults to English — only the
    language name reaches the isolated writer, never OPERATOR.md.

    The main agent does NOT read the fact files and does NOT author the prose: it
    calls this tool, then renders the returned ``report.md`` to PDF and delivers.

    Returns ``{report_md_path, language, status, returncode, leak_findings,
    stderr_tail}``. **Honesty:** ``status="ok"`` only on a zero exit AND non-empty
    output AND zero ``leak_findings``. On any non-``ok`` status — including a leak —
    the report is NOT kept as a clean artifact: on codex failure nothing is
    written; on a leak the output is written to ``report.leaky.md`` (for
    inspection) and ``report.md`` is not produced."""
    pdir = resolve_project(project)
    lang = language or _operator_language() or "English"
    report_path = pdir / "report" / "report.md"
    prompt = assemble.build_prompt(pdir, language=lang)
    res = _drive(prompt)
    out: Dict[str, Any] = {
        "report_md_path": str(report_path),
        "language": lang,
        "status": res["status"],
        "returncode": res["returncode"],
        "leak_findings": [],
        "stderr_tail": res["stderr_tail"],
    }
    if res["status"] != "ok":
        out["error"] = res.get("error")
        return out

    report = res["stdout"]
    leaks = leak_findings(report)
    out["leak_findings"] = leaks
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if leaks:
        # DO NOT keep a leaky report under the clean name. Quarantine it for
        # inspection and report an honest non-ok status.
        leaky_path = report_path.with_name("report.leaky.md")
        leaky_path.write_text(report, encoding="utf-8")
        if report_path.exists():
            report_path.unlink()  # never leave a stale clean report next to a leaky run
        out["status"] = "leak"
        out["error"] = "report contains leaked identifiers/machinery; not kept as report.md"
        out["leaky_md_path"] = str(leaky_path)
        return out

    report_path.write_text(report, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #

_TOOLS = {
    "summary_write": summary_write,
}


def build_app() -> FastMCP:
    """Build the stdio MCP app exposing ``summary_write``."""
    app = FastMCP("human-summary")
    for name, fn in _TOOLS.items():
        app.tool(name=name)(fn)
    return app
