"""On-disk layout, project/worker resolution, and role parsing for the swarm.

This is the single source of truth for *where everything lives* — shared by
``danus.execution`` (the loop + scaffolding) and ``danus.orchestration`` (the CLI
verbs). Every path/name is derived here so the two halves can never drift.

Layout (a project root holds the *shared* stores; each worker has its own home,
which is also the codex working dir / LocalMemory root)::

    <agents_root>/<project>/           # = DANUS_PROJECT_DIR (shared)
      global_memory/  fact_graph/      # created lazily by core on first write
      project.json                     # roster + metadata
      .run_deadline                    # optional epoch ceiling
      workers/<worker>/                # worker home (codex cwd, LocalMemory root)
        AGENTS.md -> agents/contracts/worker.md   # the static contract codex reads
        .agents/skills -> agents/skills/worker    # the worker skills
        .codex/config.toml                        # MCP = danus gateway, role=worker
        TASK.md                                   # per-round assignment (danus assign)
        local_memory/                             # worker-private (codex writes)
        .role .pid .pid.lock .stop .status.json  logs/

Key defaults:
  - the MCP server is launched as the installed package ``python -m danus.gateway``
    (a pinned interface) — never an absolute path to a server file;
  - ``agents_root`` defaults to ``runtime/projects`` under the cwd, overridable with
    ``DANUS_AGENTS_ROOT``;
  - the worker contract + skills are resolved at CALL time from env
    (``DANUS_WORKER_CONTRACT`` / ``DANUS_WORKER_SKILLS``), defaulting to the
    repo-root ``agents/`` tree — testable + relocatable.

Everything reads env at CALL time (not import time) to match core/gateway/verify.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------- #
# per-worker control-file names — the single source of truth                  #
# --------------------------------------------------------------------------- #

TASK_FILE = "TASK.md"
ROLE_FILE = ".role"
PID_FILE = ".pid"
LOCK_FILE = ".pid.lock"
STOP_FILE = ".stop"
STATUS_FILE = ".status.json"
LOGS_DIR = "logs"
DEADLINE_FILE = ".run_deadline"


# --------------------------------------------------------------------------- #
# roots (env read at call time)                                               #
# --------------------------------------------------------------------------- #

def repo_root() -> Path:
    """The repo root that holds the ``agents/`` tree (contracts + skills).

    The package lives at ``<repo>/danus/execution/layout.py``; the ``agents/``
    tree is its sibling ``<repo>/agents``. Used only to locate the worker
    contract + skills defaults (both env-overridable)."""
    return Path(__file__).resolve().parents[2]


def agents_root() -> Path:
    """Where projects live. Override with ``DANUS_AGENTS_ROOT``; defaults to
    ``runtime/projects`` under the current working directory (OSS default)."""
    env = os.environ.get("DANUS_AGENTS_ROOT")
    if env:
        return Path(env).resolve()
    return (Path.cwd() / "runtime" / "projects").resolve()


def worker_md() -> Path:
    """The worker contract codex auto-reads (symlinked to AGENTS.md). Pinned path
    ``agents/contracts/worker.md``; override with ``DANUS_WORKER_CONTRACT``."""
    env = os.environ.get("DANUS_WORKER_CONTRACT")
    if env:
        return Path(env).resolve()
    return repo_root() / "agents" / "contracts" / "worker.md"


def worker_skills_dir() -> Path:
    """The worker skills dir (symlinked to .agents/skills). Pinned path
    ``agents/skills/worker``; override with ``DANUS_WORKER_SKILLS``."""
    env = os.environ.get("DANUS_WORKER_SKILLS")
    if env:
        return Path(env).resolve()
    return repo_root() / "agents" / "skills" / "worker"


# --------------------------------------------------------------------------- #
# project / worker dirs                                                        #
# --------------------------------------------------------------------------- #

def project_dir(project: str) -> Path:
    return agents_root() / project


def workers_dir(project: str) -> Path:
    return project_dir(project) / "workers"


def worker_dir(project: str, worker: str) -> Path:
    return workers_dir(project) / worker


def list_workers(project: str) -> List[str]:
    wd = workers_dir(project)
    if not wd.is_dir():
        return []
    return sorted(p.name for p in wd.iterdir() if p.is_dir())


def list_projects() -> List[str]:
    """Every project under the agents root (a dir holding a ``workers/`` subdir)."""
    root = agents_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "workers").is_dir())


# --------------------------------------------------------------------------- #
# typed per-worker layout (a thin convenience over the path constants)          #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class WorkerLayout:
    """Typed view of one worker home. ``dir`` is the codex cwd / LocalMemory root;
    every control file is a property so callers never re-spell the names."""

    dir: Path

    @property
    def name(self) -> str:
        return self.dir.name

    @property
    def project_dir(self) -> Path:
        # <project>/workers/<worker>  ->  <project>
        return self.dir.parents[1]

    @property
    def project(self) -> str:
        return self.project_dir.name

    @property
    def task(self) -> Path:
        return self.dir / TASK_FILE

    @property
    def role(self) -> Path:
        return self.dir / ROLE_FILE

    @property
    def pid(self) -> Path:
        return self.dir / PID_FILE

    @property
    def lock(self) -> Path:
        return self.dir / LOCK_FILE

    @property
    def stop(self) -> Path:
        return self.dir / STOP_FILE

    @property
    def status(self) -> Path:
        return self.dir / STATUS_FILE

    @property
    def logs(self) -> Path:
        return self.dir / LOGS_DIR

    @property
    def local_memory(self) -> Path:
        return self.dir / "local_memory"

    @property
    def codex_config(self) -> Path:
        return self.dir / ".codex" / "config.toml"


# --------------------------------------------------------------------------- #
# target parsing                                                              #
# --------------------------------------------------------------------------- #

def resolve_target(target: str) -> Tuple[str, Optional[str]]:
    """``"proj"`` -> (proj, None);  ``"proj/worker"`` -> (proj, worker)."""
    target = target.strip().strip("/")
    if "/" in target:
        project, worker = target.split("/", 1)
        return project, (worker or None)
    return target, None


def target_worker_dirs(target: str) -> List[Path]:
    """Worker dirs addressed by ``target`` — one (proj/worker) or all (proj)."""
    project, worker = resolve_target(target)
    if worker:
        return [worker_dir(project, worker)]
    return [worker_dir(project, w) for w in list_workers(project)]


# --------------------------------------------------------------------------- #
# role spec                                                                   #
# --------------------------------------------------------------------------- #

_ROLE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*?):(\d+)$")


def parse_roles(spec: str) -> List[Tuple[str, str]]:
    """``"high:3,xhigh:4"`` -> ``[("high","high"), ("high2","high"),
    ("high3","high"), ("xhigh","xhigh"), …]``. Returns (worker_name, base_role)
    pairs; the base role (digits stripped) drives the codex reasoning effort. The
    first worker of a base keeps the bare name; the rest get numeric suffixes.
    Raises ``ValueError`` on a malformed/empty spec or a count < 1."""
    out: List[Tuple[str, str]] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        m = _ROLE_RE.match(part)
        if not m:
            raise ValueError(f"bad role spec {part!r}; want e.g. high:3,xhigh:4")
        base, count = m.group(1), int(m.group(2))
        if count < 1:
            raise ValueError(f"role count must be >= 1: {part!r}")
        for i in range(1, count + 1):
            name = base if i == 1 else f"{base}{i}"
            out.append((name, base))
    if not out:
        raise ValueError("empty role spec")
    return out
