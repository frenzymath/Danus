# danus/core — the Danus data model (library)

Pure-Python, protocol-agnostic. **Read [`DATA_MODEL.md`](DATA_MODEL.md) first** —
the authoritative spec. This is the API quick reference.

**Code only touches the fixed data structures (the JSONL files + the fact-graph
nodes).** Everything behavioral — when to publish a finding, when to send it to
the verifier, when to promote it to a fact, the control loop, strategy — is
**prose** (prompts/skills), not code. That boundary is deliberate; don't add
"orchestration" code here.

```
danus/core/
  DATA_MODEL.md      ← detailed spec (read first)
  local_memory.py    LocalMemory   — per-worker private, rough recall log
  global_memory.py   GlobalMemory  — project-shared, strongly typed findings
  factgraph.py       FactGraph     — project-shared, verified content-addressed DAG
  schema.py          Fact, GLOBAL_KINDS, STATUSES, compute_fact_id
  bm25.py            BM25 recall
  _util.py           append-only JSONL helpers
  tests/test_core.py smoke test
```

Design: local/global memory use an append-only-JSONL + per-channel + BM25
mechanism; the fact-graph node and `compute_fact_id` are deliberately thin
(5 frontmatter fields, no status/verifier_outcome/claim_summary in the node; the
**glossary is kept** — it makes the graph readable). Stores take **explicit
roots** — orchestration decides where worker/project directories live.

## API

```python
from core import LocalMemory, GlobalMemory, FactGraph

# local memory (per worker; root = the worker's own dir) — rough recall.
# No CLI wraps this: the worker reads/writes/greps its own files directly.
lm = LocalMemory(worker_dir)
lm.append("notes", {"thought": "..."}); lm.read("notes")

# global memory (shared; root = the project dir) — typed findings
gm = GlobalMemory(project_dir)
gid = gm.append("counterexample", claim="...", evidence="...QED",   # evidence required
                author="worker_xhigh", glossary={"X": "a manifold"})  # for verifiable kinds
gm.append("master_guidance", claim="...", evidence="GPT-5.5-pro: ...", author="main_agent")
gm.set_status(gid, "verified", fact_id="<id>")   # agent-driven status note
gm.read("plan"); gm.search("query", kinds=["dead_end"])

# fact graph (shared; root = the project dir) — verified truth
fg = FactGraph(project_dir)
fid = fg.add(problem_id="KMMP", author="KMMP_high", statement="...", proof="...",
             predecessors=["<id>"], glossary_introduces={"K_F": "canonical class of F"})
fg.undefined_symbols(statement="...", proof="...", predecessors=["<id>"])  # coverage check
fg.get_raw(fid); fg.list(); fg.predecessors(fid); fg.glossary(); fg.descendants(fid)
fg.revoke(fid, reason="...")     # cascades to dependents
```

**The promotion flow is prose, not a function.** When a verifiable global-memory
finding passes the verifier, the agent (per its prompt) calls `fg.add(...)` to
write the fact and `gm.set_status(id, "verified", fact_id)` to back-link. The
library does not bundle that into a `promote()` — the decision and the verify
call are the agent's.

## Invariants the library enforces (mechanical only)

- Verifiable global-memory kinds require non-empty `evidence`.
- `fact_id` is content-addressed; identical content ⇒ identical id (dedup).
- `FactGraph.add` refuses a revoked predecessor; `revoke` cascades to descendants.
- Append-only everywhere; status is an appended note folded at read.

Enforced by **prose**, not code: "global memory is awareness, never a correctness
source — a proof may only cite a `fact_id`"; "no handwave / chart-position refs."
(Symbol coverage *is* mechanical — `FactGraph.undefined_symbols`, run by
`fact submit` — but the prompt still tells the worker to define its symbols.)

## Test

```bash
python3 danus/core/tests/test_core.py
```

## Known follow-ups

- BM25 re-tokenizes per call → persistent index (sqlite FTS5),
  ranking preserved. Perf only.
- The derived board/index (fast cross-worker BM25 over `facts/`) — regenerate
  from `facts/` if/when needed; not stored as a separate truth.
