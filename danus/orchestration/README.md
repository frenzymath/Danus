# danus/orchestration — the `danus` CLI verbs

The operator's lifecycle commands. **Verbs/UX only** — the on-disk layout, the
round loop, and scaffolding live in `danus/execution`; this module parses arguments
and calls into it. Run via `bin/danus`.

```
danus/orchestration/
  cli.py        the verbs: list / new / assign / finalize / start / status / stop
  __main__.py   `python -m danus.orchestration` (what bin/danus execs)
  tests/{test_cli_verbs.py, test_orchestration.py}
```

## Verbs

| verb | does |
|---|---|
| `list [--json]` | projects + live worker counts + model |
| `new <p> [--roles high:3,xhigh:4] [--model M]` | → `execution.scaffold.do_new` |
| `assign <p>/<w> (--task/--file/--stdin)` | overwrite that worker's `TASK.md` |
| `finalize <p> [<fact_id>…]` | record target(s) in `TARGET.md` (no id ⇒ suggest terminal facts); records only, does not stop workers |
| `start <p>[/<w>]` | → `execution.scaffold.spawn_loop` (idempotent via `.pid.lock`) |
| `status <p>[/<w>] [--json]` | per-worker liveness + round + `stuck?` soft signal |
| `stop <p>[/<w>] [--force]` | graceful `.stop` / `--force` `killpg` |

## Notes

- Liveness is **zombie-aware** (`os.kill(pid,0)` + a `/proc/<pid>/stat` Z-state
  check), so `status`/`list` don't lie and `start` can restart a crashed worker.
- No `assign`-all, no pause/resume — restart = `stop` then `start`.
- Touches core only indirectly: `new` creates the empty `global_memory/`/`fact_graph/`
  dirs (populated lazily by core on first write); it never writes the truth stores.

## Tests

`python -m pytest danus/orchestration/` (offline; fake codex + stub project).
