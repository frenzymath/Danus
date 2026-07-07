# Danus — CLI & Tools Reference

Danus has two control surfaces:

1. **The `danus` CLI** — lifecycle verbs you (or the main agent on your behalf) run
   to manage projects and workers.
2. **The MCP tools** — what the main agent calls in-session. Three MCP servers are
   wired in `.mcp.json`: the role-gated **`danus`** gateway, **`write-paper`**, and
   **`human-summary`**.

You mostly talk to the main agent in natural language; it runs the CLI verbs and
calls the tools. This page is the reference for what exists.

---

## The `danus` CLI

Run via `bin/danus` (which sources `scripts/env.sh`). Every verb names a project;
there is no default project.

| verb | form | what it does |
|---|---|---|
| `list` | `danus list [--json]` | all projects + live worker counts + model |
| `new` | `danus new <project> [--roles high:3,xhigh:4] [--model M]` | scaffold a project + worker dirs; default roster 3 `high` + 4 `xhigh` |
| `assign` | `danus assign <project>/<worker> (--task "…" \| --file P \| --stdin)` | write that worker's per-round `TASK.md` (**replaces**, not appends) |
| `finalize` | `danus finalize <project> [--paper <paper_id>] [<fact_id> …]` | record the approved target theorem(s) in the paper's `TARGET.md` (what write-paper reads; default paper → `<project>/TARGET.md`, a non-default `--paper` → `<project>/papers/<paper_id>/TARGET.md`). **With no id:** print candidate terminal facts as suggestions (writes nothing) |
| `start` | `danus start <project>[/<worker>]` | launch the autonomous worker loop(s) |
| `status` | `danus status <project>[/<worker>] [--json]` | per-worker liveness + round + last activity (`stuck?` is a soft signal) |
| `stop` | `danus stop <project>[/<worker>] [--force]` | graceful (finish the round, exit at the boundary) or `--force` (kill the process group) |

Notes:
- `finalize` only **records** the answer; it does not stop workers. Deciding a
  verified fact is *the answer* is your call (the main agent surfaces it).
- `start` launches each worker detached in its own process group, so it survives
  your session; `stop --force` can therefore kill a live worker and its in-flight
  codex child.

---

## MCP server 1 — `danus` (the gateway): the door to the truth stores

The gateway is **role-gated**: what a caller can see depends on `DANUS_ROLE`. The
main agent runs as `role=main`.

**The six tools** (a trailing `?` marks an optional argument):

| tool | args | what it does |
|---|---|---|
| `gm_add` | `kind, claim, evidence, verifiable?, glossary?, links?, project?` | publish a finding to shared global memory |
| `gm_search` | `query, kinds?, limit_per_kind?, project?` | search global-memory findings |
| `fact_submit` | `statement, proof, predecessors?, glossary_introduces?, intuition?, source_id?, external_refs?` | **the write-gate** — verify, then write the fact iff `correct`, always trace the verdict |
| `fact_search` | `query, limit?, project?` | search the verified fact graph |
| `fact_revoke` | `fact_id, reason, project?` | cascade-revoke a fact + its dependents |
| `search_arxiv_theorems` | `query, num_results?` | semantic search over arXiv theorem statements |

**Who can see what (`danus/gateway/roles.py`):**

| role | tools |
|---|---|
| **worker** | `gm_add`, `gm_search`, `fact_submit`, `fact_search`, `search_arxiv_theorems` |
| **main** | `gm_add`, `gm_search`, `fact_search`, `fact_revoke`, `search_arxiv_theorems` (**no `fact_submit`**) |
| **verifier** (the fact-checking verifier behind `fact_submit`) | `search_arxiv_theorems` only (read-only) |

The main agent thus **cannot write a fact** and **cannot** even see `fact_submit`;
the verifier can write nothing. See `security-and-trust.md`.

---

## MCP server 2 — `write-paper`: fact graph → publishable paper

Six tools (`danus/write_paper/server.py`), each wrapping an isolated codex role.
The main agent calls them with small structured args; the heavy bytes (style guide,
fact-graph math) are assembled inside the tool and never enter the main agent's
context. Each tool returns a small honest envelope (status + paths + flags + a
`log_path` to a per-call diagnostic log), never the full `.tex`.

| tool | role | what it does |
|---|---|---|
| `paper_subgraph` | (curation, no codex) | return a compact, deterministic statements-only skeleton of the target-fact closure for the main agent to read and pick from — no codex, no writes; feed the chosen `fact_ids` to `paper_write` |
| `paper_write` | writer | draft the first complete `main.tex` from the target closure + house style |
| `reference_audit` | reference auditor | **offline** — flag bibliography entries it cannot vouch for (no tools/network) |
| `reference_verify` | reference verifier | **online** — verify flagged citations (arXiv + web) and update the reference ledger in place |
| `paper_revise` | reviser | revise `main.tex` for compile fixes / operator annotations / citation fixes (in-tool compile-retry loop) |
| `paper_verify_math` | (math re-verification) | re-check the whole paper's math, as written, through a dedicated verifier before delivery |

Most tools take an optional `paper_id` — a project can hold multiple papers (the
default paper uses the legacy `<project>/paper/` workspace; any other `paper_id`
gets an isolated `<project>/papers/<paper_id>/`). See the write-paper skill README
(`.claude/skills/write-paper/README.md`) for the full workflow.

---

## MCP server 3 — `human-summary`: fact graph → reader report

| tool | what it does |
|---|---|
| `summary_write` | render a human-readable, id-free progress report (compiled PDF) from the fact graph — precise problem statement, partial results with real proof sketches, the main obstacle, a neutral timeline, and the remaining lemma |

`summary_write` takes an optional `language` (else it follows the operator's
language in `OPERATOR.md`).

---

## Main-agent skills (invoked in-session, not MCP tools)

The main agent also has Claude Code **skills** under `.claude/skills/`:
`initialize` (first-run setup), `elaboration` (the strategy synthesis),
`consult` (the strategy consult), `human-summary`, and `write-paper`. These
orchestrate the tools and CLI above; see `operating-guide.md` for how they fit the
lifecycle.

---

## The persistent services (run via `scripts/services.sh`)

| service | port | required? |
|---|---|---|
| `verify` | 127.0.0.1:8091 | **yes** — no verify ⇒ `fact_submit` fails ⇒ no facts |
| `dashboard` | 127.0.0.1:8099 | optional (read-only view; port-forward to see it) |

```bash
bash scripts/services.sh up verify            # required before any proving
bash scripts/services.sh up dashboard <p>     # optional
bash scripts/services.sh status | logs <svc> [-f] | down <svc>|all
```

See `operations.md` for the runbook and `configuration.md` for the environment
variables that tune all of the above.
