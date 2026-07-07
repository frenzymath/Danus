"""Offline tests for danus.observability — no network, no codex, no API spend.

Builds a temp project dir with a few fact ``.md`` files + a couple of
``global_memory/*.jsonl`` channels (and a spend ledger), then exercises both:

  * the pure builder functions (``build_overview`` / ``build_factgraph`` /
    ``build_channels`` / ``build_channel``) directly, and
  * the HTTP routes via Starlette's ``TestClient`` (httpx is present) — this
    covers app wiring, the 404 on an unknown channel, and that ``GET /`` serves
    the static page from disk.

No browser is involved; the static assets pull CDN scripts only in a real
browser, so serving the HTML file is a pure filesystem read here.

Runs standalone (``python -m danus.observability.tests.test_observability``) and
under pytest.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from danus.observability import app as obs_app  # the FastAPI instance
from danus.observability.app import (
    build_channel,
    build_channels,
    build_factgraph,
    build_overview,
)


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


def _fact_md(fact_id, author, predecessors, statement, proof, intuition="", problem_id="P"):
    preds = "[" + ", ".join(predecessors) + "]"
    parts = [
        "---",
        f"fact_id: {fact_id}",
        f"problem_id: {problem_id}",
        f"author: {author}",
        f"predecessors: {preds}",
        "---",
        "## statement",
        statement,
        "## proof",
        proof,
    ]
    if intuition:
        parts += ["## intuition", intuition]
    return "\n".join(parts) + "\n"


def _seed_project(root: Path) -> None:
    """A tiny 3-node DAG (a -> b -> c) plus two global-memory channels + spend."""
    facts = root / "fact_graph" / "facts"
    facts.mkdir(parents=True)
    (facts / "aaaa.md").write_text(
        _fact_md("aaaa1111", "worker_high", [], "Base lemma $n+0=n$.", "By identity."),
        encoding="utf-8")
    (facts / "bbbb.md").write_text(
        _fact_md("bbbb2222", "worker_high", ["aaaa1111"], "Middle result.", "Use aaaa1111."),
        encoding="utf-8")
    (facts / "cccc.md").write_text(
        _fact_md("cccc3333", "worker_xhigh", ["bbbb2222"], "Top result $\\int f$.", "Use bbbb2222.",
                 intuition="the deep one"),
        encoding="utf-8")
    # a fact whose file has no fact_id frontmatter -> falls back to filename stem
    (facts / "dddd4444.md").write_text(
        "## statement\nStandalone axiom.\n## proof\ntrivial.\n", encoding="utf-8")

    mem = root / "global_memory"
    mem.mkdir(parents=True)
    with (mem / "plan.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"author": "main", "claim": "reduce to q>=2",
                             "evidence": "", "timestamp_utc": "2026-07-01T10:00:00"}) + "\n")
        fh.write("   \n")  # blank line -> skipped
        fh.write("{not valid json\n")  # malformed -> skipped
        fh.write(json.dumps({"author": "main", "claim": "try route X", "evidence": "e",
                             "timestamp_utc": "2026-07-02T09:00:00"}) + "\n")
    with (mem / "verification.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"author": "w", "verdict": "correct", "fact_id": "aaaa1111",
                             "claim": "ok", "timestamp_utc": "2026-07-01T11:00:00"}) + "\n")
        fh.write(json.dumps({"author": "w", "verdict": "wrong", "claim": "no",
                             "timestamp_utc": "2026-07-01T12:00:00"}) + "\n")

    spend = root / "spend"
    spend.mkdir(parents=True)
    with (spend / "consult.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"cost_usd": 1.25}) + "\n")
        fh.write(json.dumps({"cost_usd": 0.75}) + "\n")


# --------------------------------------------------------------------------- #
# pure builder functions (project passed explicitly — no env needed)          #
# --------------------------------------------------------------------------- #

def test_overview_counts():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed_project(root)
        ov = build_overview(root)
        assert ov["project"] == root.name
        assert ov["facts"] == 4  # 3 seeded + 1 filename-stem fallback
        assert ov["facts_with_predecessors"] == 2  # bbbb, cccc
        assert ov["facts_by_author"]["worker_high"] == 2
        # only two real plan entries survive (blank + malformed skipped)
        assert ov["channel_counts"]["plan"] == 2
        assert ov["verdicts"] == {"correct": 1, "wrong": 1}
        assert ov["consult_count"] == 2
        assert ov["consult_cost_usd"] == 2.0


def test_factgraph_nodes_edges_depth():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed_project(root)
        g = build_factgraph(root)
        by_id = {n["id"]: n for n in g["nodes"]}
        assert set(by_id) == {"aaaa1111", "bbbb2222", "cccc3333", "dddd4444"}
        # depth = longest path from a leaf; the a->b->c chain gives 0,1,2
        assert by_id["aaaa1111"]["depth"] == 0
        assert by_id["bbbb2222"]["depth"] == 1
        assert by_id["cccc3333"]["depth"] == 2
        assert by_id["dddd4444"]["depth"] == 0  # isolated axiom
        assert g["max_depth"] == 2
        assert {"source": "aaaa1111", "target": "bbbb2222"} in g["edges"]
        assert {"source": "bbbb2222", "target": "cccc3333"} in g["edges"]
        assert len(g["edges"]) == 2
        # section bodies survived parsing
        assert "Base lemma" in by_id["aaaa1111"]["statement"]
        assert by_id["cccc3333"]["intuition"] == "the deep one"


def test_factgraph_cycle_guard():
    # a self/mutual cycle in predecessors must not crash the depth computation
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        facts = root / "fact_graph" / "facts"
        facts.mkdir(parents=True)
        (facts / "x.md").write_text(_fact_md("x1", "w", ["y1"], "X", "px"), encoding="utf-8")
        (facts / "y.md").write_text(_fact_md("y1", "w", ["x1"], "Y", "py"), encoding="utf-8")
        g = build_factgraph(root)  # must return, not hang/raise
        assert {n["id"] for n in g["nodes"]} == {"x1", "y1"}
        assert g["max_depth"] >= 0


def test_channels_and_channel():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed_project(root)
        chans = build_channels(root)
        kinds = {c["kind"]: c for c in chans["channels"]}
        assert len(kinds) == 11  # all GLOBAL_KINDS mirrored
        assert kinds["plan"]["count"] == 2 and kinds["plan"]["role"] == "judgment"
        assert kinds["verification"]["count"] == 2

        ch = build_channel("plan", root)
        assert ch["kind"] == "plan" and ch["count"] == 2
        # newest-first by timestamp_utc
        assert ch["entries"][0]["timestamp_utc"] == "2026-07-02T09:00:00"

        try:
            build_channel("nope", root)
            assert False, "unknown channel should raise KeyError"
        except KeyError:
            pass


def test_missing_dirs_tolerated():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)  # empty project — no fact_graph/global_memory/spend
        ov = build_overview(root)
        assert ov["facts"] == 0 and ov["consult_count"] == 0
        assert build_factgraph(root)["nodes"] == []
        assert build_channel("plan", root)["entries"] == []


# --------------------------------------------------------------------------- #
# HTTP routes via TestClient (app wiring, 404, static index)                  #
# --------------------------------------------------------------------------- #

def test_http_routes_via_testclient():
    from starlette.testclient import TestClient

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed_project(root)
        with _env(DANUS_DASHBOARD_PROJECT=str(root), DANUS_PROJECT_DIR=None):
            client = TestClient(obs_app)
            r = client.get("/api/overview")
            assert r.status_code == 200 and r.json()["facts"] == 4
            r = client.get("/api/factgraph")
            assert r.status_code == 200 and r.json()["max_depth"] == 2
            r = client.get("/api/channels")
            assert r.status_code == 200 and len(r.json()["channels"]) == 11
            r = client.get("/api/channel/plan")
            assert r.status_code == 200 and r.json()["count"] == 2
            # unknown channel -> 404
            assert client.get("/api/channel/nope").status_code == 404
            # index page served from disk (read-only file serve, no browser)
            r = client.get("/")
            assert r.status_code == 200 and "Danus" in r.text


def main() -> None:
    test_overview_counts()
    print("  [ok] overview counts (facts / authors / channels / verdicts / spend)")
    test_factgraph_nodes_edges_depth()
    print("  [ok] factgraph nodes/edges + dependency depth (0,1,2) + max_depth")
    test_factgraph_cycle_guard()
    print("  [ok] factgraph cycle guard (mutual predecessors do not hang/crash)")
    test_channels_and_channel()
    print("  [ok] channels list (11 kinds) + channel newest-first + unknown->KeyError")
    test_missing_dirs_tolerated()
    print("  [ok] missing dirs/files tolerated -> empty, never crash")
    test_http_routes_via_testclient()
    print("  [ok] HTTP routes via TestClient (overview/factgraph/channels/channel + 404 + index)")
    print("ALL OBSERVABILITY TESTS PASSED")


if __name__ == "__main__":
    main()
