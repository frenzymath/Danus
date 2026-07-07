# danus/execution — the worker swarm (round loop + scaffolding + layout)

Where autonomous `codex` workers actually prove. This module owns the on-disk
**layout**, project/worker **scaffolding**, and the per-worker **round loop**. The
`danus` CLI (`danus/orchestration`) is a thin UX layer over this; the real lifecycle
lives here.

```
danus/execution/
  layout.py     paths + names; WorkerLayout; parse_roles("high:3,xhigh:4")
  scaffold.py   do_new (project + worker dirs, .codex config, symlinks), spawn_loop
  loop.py       the round loop: kickoff prompt, run_round, stop conditions, status
  __main__.py   `python -m danus.execution <worker_dir>` → loop.main
  tests/{test_execution.py, test_loop.py}
```

## On-disk layout (`layout.py`)

`<agents_root>/<project>/` holds the shared `global_memory/` + `fact_graph/` +
`project.json`; each `workers/<worker>/` is a codex cwd with `AGENTS.md` →
`agents/contracts/worker.md`, `.agents/skills` → `agents/skills/worker`, a
`.codex/config.toml` (MCP = `python -m danus.gateway`, `DANUS_ROLE=worker`,
`DANUS_VERIFY_URL`, `tool_timeout_sec=3600`), `TASK.md`, `local_memory/`, and the
control files (`.status.json` `.pid` `.stop` `logs/`). `agents_root` =
`DANUS_AGENTS_ROOT` (default `runtime/projects`).

## The round loop (`loop.py`)

A **round = one `codex exec` continuation session** that resumes from persisted
memory (NOT one increment). Launched detached in its **own process group**
(`start_new_session`), so it survives your shell and `stop --force` can `killpg` the
loop + its codex child. Stop conditions checked at the round boundary: `.stop` flag,
`.run_deadline`, `DANUS_MAX_ROUNDS` (0 = unlimited), `DANUS_MAX_CONSEC_FAILURES`
(5). Config read at call time (`DANUS_ROUND_HARD_TIMEOUT` 4h, `DANUS_ROUND_BEAT` 5s).
`.status.json` is written atomically. **Resumability is continuity in the stores**,
not process state — a fresh `start` rebuilds context from memory + the fact graph.

## Connects to

Reads `TASK.md` (from `danus assign`) + `master_guidance` (strategy). Writes facts
only via a worker's `fact_submit` (gateway → verify). The loop itself never writes
the truth stores — it only scrapes the resulting `fact_id` from the round log for
status.

## Tests

`python -m pytest danus/execution/` (offline; a fake codex stub drives the loop /
stop / scaffolding).
