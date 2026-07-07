"""Shared pure primitives for the artifact renderers.

The machinery ``danus.write_paper`` and ``danus.human_summary`` share:

- ``resolve_project`` — the ``DANUS_AGENTS_ROOT`` / ``DANUS_PROJECT_DIR``
  resolution with path-escape validation;
- ``section`` — the BEGIN/END prompt-section wrapper;
- ``read_fixed`` / ``read_project`` — verbatim, fail-loud file reads;
- ``body_sections`` — the frontmatter-stripping fact-body scrub;
- ``classify_outcome`` — the honesty classifier over a ``CompletedProcess`` or a
  raised exception, with the "no artifact"/"no report" noun parameterized;
- ``leak_findings`` — a generic leak scanner; the caller supplies its own patterns.

No network, no codex here; every function is pure/testable.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_STDERR_TAIL_CHARS = 2000


# --------------------------------------------------------------------------- #
# project resolution (env read at CALL time — testable / reconfigurable)      #
# --------------------------------------------------------------------------- #

def resolve_project(project: Optional[str] = None) -> Path:
    """Resolve the project dir to operate on.

    ``project`` (the main agent's per-call selector) names a project under
    ``DANUS_AGENTS_ROOT`` (``<root>/<project>``); the name is validated to a
    single path segment so it can never escape the agents root. With no
    ``project`` we fall back to ``DANUS_PROJECT_DIR``."""
    agents_root = os.environ.get("DANUS_AGENTS_ROOT", "")
    project_dir = os.environ.get("DANUS_PROJECT_DIR", "")
    if project:
        if not agents_root:
            raise RuntimeError("DANUS_AGENTS_ROOT is not set; cannot resolve a project by name")
        if not PROJECT_NAME_RE.match(project):
            raise RuntimeError(f"invalid project name: {project!r}")
        pdir = Path(agents_root) / project
        if not pdir.is_dir():
            raise RuntimeError(f"no such project: {project!r} (under {agents_root})")
        return pdir
    if not project_dir:
        raise RuntimeError("DANUS_PROJECT_DIR is not set and no project was given")
    return Path(project_dir)


# --------------------------------------------------------------------------- #
# prompt section helpers                                                      #
# --------------------------------------------------------------------------- #

def section(name: str, body: str) -> str:
    """Wrap ``body`` in explicit BEGIN/END delimiters so tests can assert a
    section's presence/absence and codex can navigate the prompt."""
    return f"\n\n===== BEGIN {name} =====\n{body}\n===== END {name} =====\n"


def read_fixed(skill_dir: Path, rel: str) -> str:
    """Read a fixed skill file **verbatim, in full**. Fail loudly if missing —
    never emit a partial prompt with a silently-dropped required file."""
    path = Path(skill_dir) / rel
    if not path.is_file():
        raise FileNotFoundError(
            f"required fixed file is missing: {path} (skill_dir={skill_dir})"
        )
    return path.read_text(encoding="utf-8")


def read_project(project_dir: Path, rel: str) -> str:
    """Read a required per-project file verbatim; fail loudly if missing."""
    path = Path(project_dir) / rel
    if not path.is_file():
        raise FileNotFoundError(f"required project file is missing: {path}")
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# fact-body scrub                                                             #
# --------------------------------------------------------------------------- #

def body_sections(raw: str) -> str:
    """The fact's body — everything from the first ``## `` heading on (i.e. the
    ``## statement`` / ``## proof`` / ``## intuition`` sections), with the YAML
    frontmatter STRIPPED. This is the scrub: no ``fact_id`` / ``author`` /
    ``problem_id`` / ``predecessors`` / ``glossary_introduces`` / ``external_refs``
    reaches the codex — the renderer works from mathematics, not pipeline ids. The
    body math is preserved verbatim; never summarize a proof."""
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("## "):
            return "\n".join(lines[i:]).rstrip() + "\n"
    # No body headings (malformed fact) — return the content after the closing
    # frontmatter fence rather than leaking the frontmatter.
    if lines and lines[0].strip() == "---":
        close = next((j for j in range(1, len(lines)) if lines[j].strip() == "---"), None)
        if close is not None:
            return "\n".join(lines[close + 1:]).strip() + "\n"
    return raw.strip() + "\n"


# --------------------------------------------------------------------------- #
# codex-outcome honesty classifier                                            #
# --------------------------------------------------------------------------- #

def classify_outcome(cp_or_exc: Any, *, artifact_noun: str = "artifact") -> Dict[str, Any]:
    """Classify a codex run honestly into a small dict.

    ``cp_or_exc`` is either a ``subprocess.CompletedProcess`` (the driver
    returned) or the exception the driver raised (``TimeoutExpired`` /
    ``FileNotFoundError``). Returns ``{status, returncode, stdout, stderr_tail}``
    plus an ``error`` message when not ``ok``. ``status="ok"`` requires a zero exit
    code AND non-empty stdout — a nonzero exit, a timeout, a missing binary, or
    empty stdout is never reported as success. ``artifact_noun`` names the thing
    that was expected ("artifact" / "report") for the empty-stdout message."""
    if isinstance(cp_or_exc, subprocess.TimeoutExpired):
        return {"status": "timeout", "returncode": None, "stdout": "",
                "stderr_tail": "", "error": f"codex timed out after {cp_or_exc.timeout}s"}
    if isinstance(cp_or_exc, FileNotFoundError):
        return {"status": "error", "returncode": None, "stdout": "",
                "stderr_tail": "", "error": f"codex binary not found: {cp_or_exc}"}

    cp = cp_or_exc
    stdout = cp.stdout or ""
    stderr_tail = (cp.stderr or "")[-_STDERR_TAIL_CHARS:]
    if cp.returncode != 0:
        return {"status": "error", "returncode": cp.returncode, "stdout": stdout,
                "stderr_tail": stderr_tail,
                "error": f"codex exited with nonzero code {cp.returncode}"}
    if not stdout.strip():
        return {"status": "error", "returncode": cp.returncode, "stdout": "",
                "stderr_tail": stderr_tail,
                "error": f"codex produced empty stdout (no {artifact_noun})"}
    return {"status": "ok", "returncode": cp.returncode, "stdout": stdout,
            "stderr_tail": stderr_tail}


# --------------------------------------------------------------------------- #
# generic leak scanner                                                        #
# --------------------------------------------------------------------------- #

def leak_findings(text: str, patterns: Sequence[Tuple[str, str]]) -> List[str]:
    """Every leak-pattern hit in ``text`` (human-readable). Each ``patterns`` entry
    is ``(regex, label)``; the caller supplies the pattern set appropriate to its
    artifact. Empty list ⇒ the text is clean of every supplied pattern."""
    hits: List[str] = []
    for pattern, label in patterns:
        m = re.search(pattern, text)
        if m:
            hits.append(f"{label}: matched {m.group(0)!r}")
    return hits
