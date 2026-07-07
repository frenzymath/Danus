"""Danus observability — a strictly read-only monitoring dashboard for one
project's fact graph and global memory.

A single self-contained FastAPI app serving a one-page client (echarts + KaTeX +
markdown-it via CDN — no build step). It re-parses the on-disk stores under a
project dir and NEVER writes:

  <project>/fact_graph/facts/*.md         the verified-fact DAG
  <project>/global_memory/<kind>.jsonl    categorized findings (the 11 kinds)
  <project>/spend/consult.jsonl       pro-consult cost ledger (optional)

Decoupled by design: it imports no danus.core runtime module. The channel set is
a plain data constant here (mirrors core.schema.GLOBAL_KINDS); if core changes it,
re-sync ``CHANNELS`` below.

Config is read at CALL time from args / env (never at import): project dir from
``--project`` / ``DANUS_DASHBOARD_PROJECT`` / ``DANUS_PROJECT_DIR``; bind
127.0.0.1:8099 (loopback only) by default.

Run:
    python -m danus.observability --project /path/to/project [--port 8099]
    DANUS_PROJECT_DIR=/path/to/project python -m danus.observability
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"

# ------------------------------------------------------------------------- #
# channels — global-memory kinds in display order, each with a semantic role  #
# tag the client uses to color/group them. Mirrors danus.core GLOBAL_KINDS    #
# (kept as data on purpose — the dashboard imports no core runtime module).   #
# ------------------------------------------------------------------------- #
CHANNELS = [
    ("conclusion", "result"), ("example", "result"), ("counterexample", "result"),
    ("proof_attempt", "result"), ("plan", "judgment"), ("direction", "judgment"),
    ("obstacle", "deadend"), ("dead_end", "deadend"), ("verification", "verify"),
    ("elaboration", "strategy"), ("master_guidance", "strategy"),
]
_CHANNEL_KINDS = {k for k, _ in CHANNELS}


# ------------------------------------------------------------------------- #
# config — resolved at CALL time (never at import)                           #
# ------------------------------------------------------------------------- #

def _project_dir() -> Path:
    p = os.environ.get("DANUS_DASHBOARD_PROJECT") or os.environ.get("DANUS_PROJECT_DIR")
    if not p:
        raise RuntimeError("no project dir — set --project / DANUS_PROJECT_DIR")
    return Path(p)


# on-disk layout, centralized so a layout change touches one spot.
def _facts_dir(project: Path) -> Path:
    return project / "fact_graph" / "facts"


def _channel_file(project: Path, kind: str) -> Path:
    return project / "global_memory" / f"{kind}.jsonl"


def _spend_file(project: Path) -> Path:
    return project / "spend" / "consult.jsonl"


# ------------------------------------------------------------------------- #
# parsing (self-contained; never writes; tolerant of partial/malformed data) #
# ------------------------------------------------------------------------- #

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_fact(text: str) -> Dict[str, Any]:
    """fact md = YAML-ish frontmatter (fact_id / problem_id / author /
    predecessors) + ``## statement`` / ``## proof`` / ``## intuition`` sections."""
    m = _FM.match(text)
    fm: Dict[str, Any] = {}
    body = text
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                fm[k] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()] if inner else []
            else:
                fm[k] = v
    secs = {"statement": "", "proof": "", "intuition": ""}
    cur: Optional[str] = None
    for line in body.splitlines():
        h = re.match(r"^##\s+(\w+)", line)
        if h and h.group(1).lower() in secs:
            cur = h.group(1).lower()
            continue
        if cur:
            secs[cur] += line + "\n"
    return {
        "fact_id": fm.get("fact_id", ""),
        "problem_id": fm.get("problem_id", ""),
        "author": fm.get("author", ""),
        "predecessors": fm.get("predecessors", []) or [],
        "statement": secs["statement"].strip(),
        "proof": secs["proof"].strip(),
        "intuition": secs["intuition"].strip(),
    }


def _load_facts(project: Path) -> List[Dict[str, Any]]:
    d = _facts_dir(project)
    if not d.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for f in sorted(d.glob("*.md")):
        try:
            fact = _parse_fact(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not fact["fact_id"]:
            fact["fact_id"] = f.stem
        out.append(fact)
    return out


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read a .jsonl line-by-line, skipping blank/malformed lines. Missing file
    -> empty. Never raises on bad data (stores are appended while we read)."""
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _load_channel(project: Path, kind: str) -> List[Dict[str, Any]]:
    return _load_jsonl(_channel_file(project, kind))


def _load_spend(project: Path) -> List[Dict[str, Any]]:
    return _load_jsonl(_spend_file(project))


def _depths(deps: Dict[str, List[str]]) -> Dict[str, int]:
    """depth = longest path from a leaf (no-predecessor) node up to this one —
    how many dependency layers a fact is built on. Leaves = 0. Cycle-guarded (a
    content-addressed DAG shouldn't cycle, but the store may be mid-write)."""
    depth: Dict[str, int] = {}

    def get(fid: str, stack: frozenset) -> int:
        if fid in depth:
            return depth[fid]
        if fid in stack:  # cycle guard
            return 0
        ps = deps.get(fid, [])
        d = 0 if not ps else 1 + max(get(p, stack | {fid}) for p in ps)
        depth[fid] = d
        return d

    for fid in deps:
        get(fid, frozenset())
    return depth


# ------------------------------------------------------------------------- #
# typed response models (the four /api/* payloads)                           #
# ------------------------------------------------------------------------- #

class Overview(BaseModel):
    project: str
    facts: int
    facts_with_predecessors: int
    facts_by_author: Dict[str, int]
    channel_counts: Dict[str, int]
    verdicts: Dict[str, int]
    consult_count: int
    consult_cost_usd: float
    updated_at: float


class GraphNode(BaseModel):
    id: str
    author: str
    problem_id: str
    statement: str
    proof: str
    intuition: str
    predecessors: List[str]
    depth: int


class GraphEdge(BaseModel):
    source: str
    target: str


class FactGraphResp(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    max_depth: int


class ChannelInfo(BaseModel):
    kind: str
    role: str
    count: int


class ChannelsResp(BaseModel):
    channels: List[ChannelInfo]


class ChannelResp(BaseModel):
    kind: str
    count: int
    entries: List[Dict[str, Any]]


# ------------------------------------------------------------------------- #
# route implementations (pure functions — testable offline without a client) #
# ------------------------------------------------------------------------- #

def build_overview(project: Optional[Path] = None) -> Dict[str, Any]:
    project = project or _project_dir()
    facts = _load_facts(project)
    counts = {k: len(_load_channel(project, k)) for k, _ in CHANNELS}
    verdicts: Dict[str, int] = {}
    for e in _load_channel(project, "verification"):
        v = e.get("verdict", "?")
        verdicts[v] = verdicts.get(v, 0) + 1
    spend = _load_spend(project)
    total_cost = round(sum(float(s.get("cost_usd", 0.0) or 0.0) for s in spend), 2)
    by_author: Dict[str, int] = {}
    for f in facts:
        by_author[f["author"]] = by_author.get(f["author"], 0) + 1
    leaves = sum(1 for f in facts if not f["predecessors"])
    return {
        "project": project.name,
        "facts": len(facts),
        "facts_with_predecessors": len(facts) - leaves,
        "facts_by_author": by_author,
        "channel_counts": counts,
        "verdicts": verdicts,
        "consult_count": len(spend),
        "consult_cost_usd": total_cost,
        "updated_at": time.time(),
    }


def build_factgraph(project: Optional[Path] = None) -> Dict[str, Any]:
    project = project or _project_dir()
    facts = _load_facts(project)
    ids = {f["fact_id"] for f in facts}
    deps = {f["fact_id"]: [p for p in f["predecessors"] if p in ids] for f in facts}
    depth = _depths(deps)
    nodes = [{
        "id": f["fact_id"], "author": f["author"], "problem_id": f["problem_id"],
        "statement": f["statement"], "proof": f["proof"], "intuition": f["intuition"],
        "predecessors": deps[f["fact_id"]],
        "depth": depth.get(f["fact_id"], 0),
    } for f in facts]
    edges = [{"source": p, "target": f["fact_id"]} for f in facts for p in deps[f["fact_id"]]]
    return {"nodes": nodes, "edges": edges, "max_depth": max(depth.values(), default=0)}


def build_channels(project: Optional[Path] = None) -> Dict[str, Any]:
    project = project or _project_dir()
    return {"channels": [{"kind": k, "role": r, "count": len(_load_channel(project, k))}
                         for k, r in CHANNELS]}


def build_channel(kind: str, project: Optional[Path] = None) -> Dict[str, Any]:
    if kind not in _CHANNEL_KINDS:
        raise KeyError(kind)
    project = project or _project_dir()
    entries = _load_channel(project, kind)
    entries.sort(key=lambda e: e.get("timestamp_utc", ""), reverse=True)
    return {"kind": kind, "count": len(entries), "entries": entries}


# ------------------------------------------------------------------------- #
# app                                                                        #
# ------------------------------------------------------------------------- #

app = FastAPI(title="danus-observability", version="0.1.0")


@app.get("/api/overview", response_model=Overview)
def overview() -> JSONResponse:
    return JSONResponse(build_overview())


@app.get("/api/factgraph", response_model=FactGraphResp)
def factgraph() -> JSONResponse:
    return JSONResponse(build_factgraph())


@app.get("/api/channels", response_model=ChannelsResp)
def channels() -> JSONResponse:
    return JSONResponse(build_channels())


@app.get("/api/channel/{kind}", response_model=ChannelResp)
def channel(kind: str) -> JSONResponse:
    try:
        return JSONResponse(build_channel(kind))
    except KeyError:
        raise HTTPException(404, f"unknown channel {kind}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    ap = argparse.ArgumentParser(description="Danus read-only fact-graph + global-memory dashboard.")
    ap.add_argument("--project", help="project dir (or set DANUS_PROJECT_DIR)")
    ap.add_argument("--host", default="127.0.0.1")  # loopback only; expose via SSH port-forward
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()
    if args.project:
        os.environ["DANUS_DASHBOARD_PROJECT"] = args.project
    project = _project_dir()  # fail fast if unset
    if not project.is_dir():
        raise SystemExit(f"project dir not found: {project}")
    import uvicorn
    print(f"danus dashboard: http://{args.host}:{args.port}/  (project: {project})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
