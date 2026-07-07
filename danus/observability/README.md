# danus/observability — the read-only dashboard

A single self-contained **FastAPI** app that shows one project's verified-fact DAG,
global-memory channels, and consult spend. **Strictly read-only and decoupled**: it
imports no `danus.core` runtime module, only ever `read_text`s the on-disk stores,
and tolerates partial/malformed data (the stores are appended while it reads).

```
danus/observability/
  app.py        the FastAPI app: parsers + 4 /api endpoints + static mount
  __main__.py   `python -m danus.observability --project <dir> [--port 8099]`
  static/       index.html + app.js (echarts / KaTeX / markdown-it, CDN, no build step)
  tests/{test_observability.py, test_observability_main.py}
```

## Endpoints (all read-only)

- `GET /api/overview` — counts, per-channel totals, verdict split, consult cost
- `GET /api/factgraph` — `{nodes, edges, max_depth}` (nodes carry statement/proof/
  intuition/predecessors/depth; deterministic sorted order)
- `GET /api/channels` — per-kind counts
- `GET /api/channel/{kind}` — entries newest-first (unknown kind → 404)
- `GET /` → `static/index.html`; `/static/*` mounted

## Binding & safety

Binds **`127.0.0.1:8099`** by default (loopback — expose via SSH port-forward, never a
public interface). Project dir resolved at call time from `--project` /
`DANUS_DASHBOARD_PROJECT` / `DANUS_PROJECT_DIR`; fails fast at launch if absent.

## Gotcha

`CHANNELS` (the 11 kinds) is a **hand-maintained data copy** of `core.GLOBAL_KINDS`
(the module deliberately imports no core runtime). If `GLOBAL_KINDS` changes,
re-sync `CHANNELS` by hand.

## Tests

`python -m pytest danus/observability/` (offline; TestClient over the routes; the
CDN browser assets are not exercised — do a one-time manual browser check once
deployed).
