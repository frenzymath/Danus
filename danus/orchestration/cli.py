"""``danus`` — the main agent's control surface over codex workers.

    danus list   [--json]
    danus new    <project> [--roles high:3,xhigh:4] [--model M]
    danus assign <project>/<worker> (--task "…" | --file P | --stdin)
    danus finalize <project> [--paper <paper_id>] [<fact_id> ...]
    danus start  <project>[/<worker>]
    danus status <project>[/<worker>] [--json]
    danus stop   <project>[/<worker>] [--force]

This module is the verbs/UX only. The worker outer loop, the on-disk layout, and
the scaffolding they drive live in ``danus.execution`` (imported here as a
library). Reads/writes only files under the project dir — the loop is autonomous;
this CLI just assigns / starts / monitors / stops it.

Notes:
  - the layout + scaffolding + config template are imported from ``danus.execution``
    (no duplicated layout / config template);
  - the verbs are mode-agnostic and identical across deployments.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import time
from pathlib import Path
from typing import Dict, List, Optional

from danus.execution import layout as L
from danus.execution.scaffold import atomic_write, do_new, spawn_loop

__all__ = [
    "do_new", "do_assign", "do_start", "do_status", "worker_status",
    "do_list", "do_stop", "do_finalize", "build_parser", "main",
]


# --------------------------------------------------------------------------- #
# read helpers                                                                 #
# --------------------------------------------------------------------------- #

def _read_pid(wl: L.WorkerLayout) -> Optional[int]:
    pf = wl.pid
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    # The pid exists — but a zombie (killed, not yet reaped by its parent) is
    # effectively dead. Linux /proc tells us the process state.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        state = stat.rsplit(")", 1)[1].split()[0]  # field after "(comm)"
        return state != "Z"
    except (OSError, IndexError):
        return True


def _read_status(wl: L.WorkerLayout) -> Dict:
    sp = wl.status
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# assign                                                                       #
# --------------------------------------------------------------------------- #

def do_assign(target: str, task: str) -> Dict:
    """Overwrite (replace, NOT append) a worker's TASK.md, ensuring a trailing
    newline. Rejects a bare project, a nonexistent worker, and an empty task."""
    project, worker = L.resolve_target(target)
    if not worker:
        raise SystemExit("assign needs a specific worker: <project>/<worker>")
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    if not wl.dir.is_dir():
        raise SystemExit(f"no such worker: {project}/{worker}")
    if not task.strip():
        raise SystemExit("refusing to assign an empty task")
    atomic_write(wl.task, task if task.endswith("\n") else task + "\n")
    return {"worker": f"{project}/{worker}", "task_file": str(wl.task)}


# --------------------------------------------------------------------------- #
# finalize                                                                     #
# --------------------------------------------------------------------------- #

def do_finalize(project: str, fact_ids: List[str],
                paper_id: Optional[str] = None) -> Dict:
    """Record the finalized target theorem(s) for a PAPER of a project in that
    paper's TARGET.md — the durable slot write-paper reads (never a guess). The
    default paper writes the LEGACY ``<project>/TARGET.md``; a non-default
    ``paper_id`` writes ``<project>/papers/<paper_id>/TARGET.md`` (its own
    workspace). One fact graph per project; per-paper targets.

    Resolves the project dir, VALIDATES every ``fact_id`` against that project's
    fact graph (refuses an id the graph does not have — you cannot record a
    phantom target), then writes the ids to the paper's TARGET.md.

    With NO ``fact_ids`` (suggestion mode): prints the candidate terminal facts
    (facts that are no other fact's predecessor — the ``assemble._terminal_facts``
    helper) as SUGGESTIONS and writes NOTHING (returns ``{"suggested": [...]}``).

    Rejections raise ``SystemExit`` (nonzero exit) with a clear message."""
    from danus.core import FactGraph
    from danus.write_paper import assemble

    pdir = L.project_dir(project)
    if not pdir.is_dir():
        raise SystemExit(f"no such project: {project}")
    fg = FactGraph(pdir)

    if not fact_ids:
        # suggestion mode: never auto-pick — just list candidate terminal facts.
        return {"project": project, "paper_id": paper_id,
                "suggested": assemble._terminal_facts(fg)}

    unknown = [fid for fid in fact_ids if not fg.exists(fid)]
    if unknown:
        raise SystemExit(
            f"cannot finalize: unknown fact id(s) in {project}: {', '.join(unknown)} "
            f"(a target must be a verified fact in the project's graph)"
        )
    # validate a non-default paper_id as a single safe path segment before writing.
    try:
        if not assemble._is_default_paper(paper_id):
            assemble._validate_paper_id(paper_id)  # type: ignore[arg-type]
    except ValueError as e:
        raise SystemExit(f"cannot finalize: {e}")
    # de-dup while preserving order
    seen: set = set()
    ids: List[str] = []
    for fid in fact_ids:
        if fid not in seen:
            seen.add(fid)
            ids.append(fid)
    path = assemble.write_target_fact_ids(pdir, ids, paper_id)
    return {"project": project, "paper_id": paper_id,
            "target_file": str(path), "target_fact_ids": ids}


# --------------------------------------------------------------------------- #
# start                                                                        #
# --------------------------------------------------------------------------- #

def _start_one(wl: L.WorkerLayout) -> str:
    """Returns 'started' / 'already-running' / 'locked'. Idempotent via an flock
    on .pid.lock; clears a stale .stop before spawning."""
    wl.dir.mkdir(parents=True, exist_ok=True)
    wl.logs.mkdir(exist_ok=True)
    lock = open(wl.lock, "w")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "locked"
        if _alive(_read_pid(wl)):
            return "already-running"
        wl.stop.unlink(missing_ok=True)  # clear a stale stop flag
        pid = spawn_loop(wl.dir)
        atomic_write(wl.pid, str(pid))
        return "started"
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def do_start(target: str, stagger: float = 0.2) -> List[Dict]:
    dirs = L.target_worker_dirs(target)
    if not dirs:
        raise SystemExit(f"no workers for target {target!r}")
    out = []
    for i, wdir in enumerate(dirs):
        if i and stagger:
            time.sleep(stagger)
        out.append({"worker": wdir.name, "result": _start_one(L.WorkerLayout(wdir))})
    return out


# --------------------------------------------------------------------------- #
# status                                                                       #
# --------------------------------------------------------------------------- #

def worker_status(wl: L.WorkerLayout) -> Dict:
    pid = _read_pid(wl)
    alive = _alive(pid)
    st = _read_status(wl)
    state = st.get("state", "—")
    now = time.time()
    last = st.get("last_round_at") or st.get("round_started_at") or st.get("updated_at")
    age = (now - last) if isinstance(last, (int, float)) else None

    if alive:
        # a round legitimately runs for hours; only flag truly stale running rounds
        rs = st.get("round_started_at")
        hard = int(os.environ.get("DANUS_ROUND_HARD_TIMEOUT", "14400"))
        if state == "running" and isinstance(rs, (int, float)) and (now - rs) > hard * 1.5:
            label = "stuck?"
        else:
            label = "working"
    else:
        label = state if state in ("stopped", "deadline", "max_rounds", "error",
                                   "terminated", "created") else "dead"
    return {
        "worker": wl.name, "pid": pid, "alive": alive, "state": state,
        "round": st.get("round", 0), "age_s": round(age, 1) if age is not None else None,
        "last_fact_id": st.get("last_fact_id"), "label": label,
    }


def do_status(target: str) -> List[Dict]:
    dirs = L.target_worker_dirs(target)
    if not dirs:
        raise SystemExit(f"no workers for target {target!r}")
    return [worker_status(L.WorkerLayout(d)) for d in dirs]


# --------------------------------------------------------------------------- #
# list                                                                         #
# --------------------------------------------------------------------------- #

def do_list() -> List[Dict]:
    """One row per project: roster + how many workers are live + model."""
    out: List[Dict] = []
    for project in L.list_projects():
        meta = {}
        mp = L.project_dir(project) / "project.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        workers = L.list_workers(project)
        live = sum(1 for w in workers
                   if _alive(_read_pid(L.WorkerLayout(L.worker_dir(project, w)))))
        out.append({"project": project, "workers": len(workers), "live": live,
                    "model": meta.get("model", "—")})
    return out


def _fmt_list(rows: List[Dict]) -> str:
    head = f"{'PROJECT':<24}{'WORKERS':>8}{'LIVE':>6}  {'MODEL':<12}"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['project']:<24}{r['workers']:>8}{r['live']:>6}  {str(r['model']):<12}")
    return "\n".join(lines) if rows else "(no projects under the agents root)"


def _fmt_status(rows: List[Dict]) -> str:
    head = f"{'WORKER':<14}{'LABEL':<12}{'STATE':<13}{'ROUND':>6}  {'AGE':>7}  {'LAST_FACT':<16}"
    lines = [head, "-" * len(head)]
    for r in rows:
        age = f"{r['age_s']:.0f}s" if r["age_s"] is not None else "—"
        lines.append(f"{r['worker']:<14}{r['label']:<12}{r['state']:<13}"
                     f"{r['round']:>6}  {age:>7}  {str(r['last_fact_id'] or '—'):<16}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# stop                                                                         #
# --------------------------------------------------------------------------- #

def _stop_one(wl: L.WorkerLayout, force: bool) -> str:
    pid = _read_pid(wl)
    if not force:
        if not _alive(pid):
            return "not-running"
        wl.stop.touch()      # graceful: loop exits at round boundary
        return "stopping (graceful)"
    # force: kill the loop's process group (loop + its codex child), then SIGKILL
    if not _alive(pid):
        wl.pid.unlink(missing_ok=True)
        return "not-running"
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    for _ in range(50):                          # up to ~5s for a clean exit
        if not _alive(pid):
            break
        time.sleep(0.1)
    if _alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    wl.pid.unlink(missing_ok=True)
    return "killed"


def do_stop(target: str, force: bool = False) -> List[Dict]:
    dirs = L.target_worker_dirs(target)
    if not dirs:
        raise SystemExit(f"no workers for target {target!r}")
    return [{"worker": d.name, "result": _stop_one(L.WorkerLayout(d), force)} for d in dirs]


# --------------------------------------------------------------------------- #
# argparse                                                                      #
# --------------------------------------------------------------------------- #

def _task_from_args(args) -> str:
    import sys
    if args.task is not None:
        return args.task
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.stdin:
        return sys.stdin.read()
    raise SystemExit("assign needs one of --task, --file, or --stdin")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="danus", description="Control codex workers.")
    sub = p.add_subparsers(dest="cmd", required=True)

    li = sub.add_parser("list", help="list all projects + live worker counts")
    li.add_argument("--json", action="store_true")

    n = sub.add_parser("new", help="scaffold a project + worker dirs")
    n.add_argument("project")
    n.add_argument("--roles", default="high:3,xhigh:4", help="e.g. high:3,xhigh:4 (default)")
    n.add_argument("--model", default=None)

    a = sub.add_parser("assign", help="write a worker's per-round TASK.md")
    a.add_argument("target", help="<project>/<worker>")
    a.add_argument("--task", default=None)
    a.add_argument("--file", default=None)
    a.add_argument("--stdin", action="store_true")

    f = sub.add_parser("finalize", help="record the finalized target fact_id(s) in "
                                        "a paper's TARGET.md (write-paper reads this)")
    f.add_argument("project")
    f.add_argument("--paper", default=None,
                   help="the paper_id (multiple papers per project). Default / 'main' "
                        "→ legacy <project>/TARGET.md; else "
                        "<project>/papers/<paper_id>/TARGET.md")
    f.add_argument("fact_ids", nargs="*",
                   help="the target fact id(s); omit to print candidate terminal facts")

    s = sub.add_parser("start", help="launch worker loop(s)")
    s.add_argument("target", help="<project> or <project>/<worker>")

    st = sub.add_parser("status", help="liveness + progress")
    st.add_argument("target", help="<project> or <project>/<worker>")
    st.add_argument("--json", action="store_true")

    sp = sub.add_parser("stop", help="stop worker loop(s)")
    sp.add_argument("target", help="<project> or <project>/<worker>")
    sp.add_argument("--force", action="store_true", help="kill now (else finish current round)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        rows = do_list()
        print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _fmt_list(rows))
    elif args.cmd == "new":
        r = do_new(args.project, roles=args.roles, model=args.model)
        print(f"created {args.project} with {len(r['workers'])} workers: "
              f"{', '.join(r['workers'])}\n  {r['project_dir']}")
    elif args.cmd == "assign":
        r = do_assign(args.target, _task_from_args(args))
        print(f"assigned {r['worker']} -> {r['task_file']}")
    elif args.cmd == "finalize":
        r = do_finalize(args.project, args.fact_ids, paper_id=args.paper)
        paper_note = f" (paper {args.paper})" if args.paper else ""
        paper_flag = f" --paper {args.paper}" if args.paper else ""
        if "suggested" in r:
            sug = r["suggested"]
            if sug:
                print(f"no fact_id given — candidate target facts for {r['project']}{paper_note} "
                      f"(terminal facts; nothing depends on them):")
                for fid in sug:
                    print(f"  {fid}")
                print(f"\nrun: danus finalize {r['project']}{paper_flag} <fact_id> [<fact_id> ...] to record")
            else:
                print(f"no candidate terminal facts in {r['project']} "
                      f"(is the fact graph empty?); nothing recorded")
        else:
            print(f"finalized target for {r['project']}{paper_note}: {', '.join(r['target_fact_ids'])}\n"
                  f"  wrote {r['target_file']}")
    elif args.cmd == "start":
        for r in do_start(args.target):
            print(f"{r['worker']}: {r['result']}")
    elif args.cmd == "status":
        rows = do_status(args.target)
        print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _fmt_status(rows))
    elif args.cmd == "stop":
        for r in do_stop(args.target, force=args.force):
            print(f"{r['worker']}: {r['result']}")
    return 0
