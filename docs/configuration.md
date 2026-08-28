# Danus — Configuration Reference

All host- and account-specific configuration lives in gitignored `config/*.env`
files; **no path or secret is hardcoded** elsewhere. `scripts/env.sh` sources the
chain and fills defaults:

```
config/codex.env  →  config/danus.env  →  runtime/runtime.env  →  built-in defaults
   (API key)          (host/account)      (machine paths, auto)   (scripts/env.sh)
```

Only `*.env.example` templates are committed; copy them to the real names and edit.
The `bin/` wrappers source `env.sh` for you. Values below are the defaults from
`scripts/env.sh` / `config/danus.env.example`.

## Codex authentication

| variable | default | meaning |
|---|---|---|
| `CODEX_API_KEY` | — | standard Codex API-key authentication; store only in gitignored `config/codex.env` |
| `CODEX_HOME` | Codex default | optional override for an intentionally isolated native Codex profile |

When `CODEX_API_KEY` is absent, Codex uses its stored native login. Run
`bin/codex login --device-auth` to authenticate with a ChatGPT subscription.
Danus does not construct or select model providers.

## Models & reasoning effort

All three codex-exec sites (workers, verifier, paper/report renderers) resolve
binary + model + effort through the shared launcher, so names are unified. Neutral
defaults apply everywhere; per-service overrides win.

| variable | default | applies to |
|---|---|---|
| `DANUS_CODEX_BIN` | `<repo>/bin/codex`, else `codex` on PATH | all codex calls |
| `DANUS_MAIN_MODEL` | `gpt-5.6-sol` | neutral default (all sites); back-compat alias `DANUS_CODEX_MODEL` |
| `DANUS_MAIN_EFFORT` | `xhigh` | neutral default effort (all sites); back-compat alias `DANUS_CODEX_EFFORT` |
| `DANUS_WORKER_MODEL` | neutral default | workers (falls back to `DANUS_MAIN_MODEL`) |
| `DANUS_VERIFY_MODEL` / `_EFFORT` | neutral | verifier — the correctness authority; keep effort at `xhigh` |
| `DANUS_WRITE_PAPER_MODEL` / `_EFFORT` | neutral | paper renderer |
| `DANUS_HUMAN_SUMMARY_MODEL` / `_EFFORT` | neutral | human-summary renderer |

The primary knobs are `DANUS_MAIN_MODEL` / `DANUS_MAIN_EFFORT`; the older
`DANUS_CODEX_MODEL` / `DANUS_CODEX_EFFORT` names are still honored as back-compat
aliases.

## Ports (all loopback)

| variable | default | service |
|---|---|---|
| `VERIFY_PORT` | `8091` | verify service (`127.0.0.1`) |
| `DASHBOARD_PORT` | `8099` | read-only dashboard (`127.0.0.1`) |
| `DANUS_VERIFY_URL` | `http://127.0.0.1:8091/verify` | where `fact_submit` posts |
| `VERIFY_HOST` | `127.0.0.1` | verify bind host (keep loopback — see security doc) |

## Runtime data locations (gitignored, under `runtime/`)

| variable | default | holds |
|---|---|---|
| `DANUS_RUNTIME` | `<repo>/runtime` | the whole self-contained runtime |
| `DANUS_AGENTS_ROOT` | `runtime/projects` | where `danus new` puts projects |
| `VERIFIER_RESULTS_DIR` | `runtime/verify-runs` | per-verification run logs |
| `DANUS_PY` | `runtime/venv/bin/python` (else system `python3`) | the engine's Python |

## Worker loop pacing (optional; engine defaults are sane)

| variable | default | meaning |
|---|---|---|
| `DANUS_ROUND_HARD_TIMEOUT` | `14400` (4h) | per-round wall-clock cap |
| `DANUS_MAX_ROUNDS` | `0` (unlimited) | round backstop |
| `DANUS_MAX_CONSEC_FAILURES` | `5` | bail after N consecutive failed rounds |
| `DANUS_ROUND_BEAT` | `5` | seconds between rounds |

## Rendering & misc

| variable | default | meaning |
|---|---|---|
| `DANUS_CHROME_BIN` | (auto-detect) | headless Chrome/Chromium for human-summary PDF |
| `TEX_ENGINE` | `pdflatex` | write-paper LaTeX engine (`xelatex`/`lualatex`/`tectonic`) |
| `DANUS_WRITE_PAPER_RUN_LOG` | on | per-call write-paper diagnostic logs (`0` disables) |
| `DANUS_PAPER_VERIFY_WHOLE_DOC_CAP` | `700000` | char budget for one whole-paper math-verify call; over it the tool reports `too_large` (the main agent decomposes — the tool never auto-splits) |

## LaTeX-git push (write-paper deliver, optional)

In `config/latex-git.env` (gitignored): `LATEX_GIT_URL`, `LATEX_GIT_TOKEN`, and
optional `LATEX_GIT_AUTHOR_NAME` / `_EMAIL`. Pushing outward is an operator-gated
action.

---

Ports and the verify HTTP contract are **pinned** cross-module interfaces
(`../ARCHITECTURE.md` §4) — do not renumber `8091`/`8099` without changing both
ends. See `operations.md` to run the services and `cli-and-tools.md` for the
commands that use these.
