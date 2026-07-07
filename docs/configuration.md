# Danus — Configuration Reference

All host- and account-specific configuration lives in gitignored `config/*.env`
files; **no path or secret is hardcoded** elsewhere. `scripts/env.sh` sources the
chain and fills defaults:

```
config/codex.env  →  config/danus.env  →  runtime/runtime.env  →  built-in defaults
   (BYO backend)      (host/account)      (machine paths, auto)   (scripts/env.sh)
```

Only `*.env.example` templates are committed; copy them to the real names and edit.
The `bin/` wrappers source `env.sh` for you. Values below are the defaults from
`scripts/env.sh` / `config/danus.env.example`.

## Codex backend (workers + verifier)

| variable | default | meaning |
|---|---|---|
| `CODEX_BACKEND` | `api` | `api` (BYO OpenAI-compatible key) or `chatgpt` (your ChatGPT login) |
| `CODEX_HOME` | `runtime/codex-home` | codex auth/config home (gitignored) |
| `CODEX_API_BASE_URL` | — | (api) your OpenAI-compatible Responses endpoint |
| `CODEX_API_MODEL` | `gpt-5.5` | (api) backend model |
| `DANUS_CODEX_API_KEY` | — | (api) key, **read at run time**, never stored in a file |

These live in `config/codex.env`. See `getting-started.md` §2 and
`scripts/setup-codex.sh`.

## Strategy consult (the system's brain)

| variable | default | meaning |
|---|---|---|
| `DANUS_CONSULT_TRANSPORT` | `gpt_pro` | `gpt_pro` \| `claude_api` \| `claude_code` \| `off` |
| `DANUS_CONSULT_API_KEY` | — | (gpt_pro) key for the OpenAI-compatible Responses API |
| `DANUS_CONSULT_BASE_URL` | `https://api.openai.com/v1` | (gpt_pro) endpoint |
| `DANUS_CONSULT_MODEL` | `gpt-5.5-pro` | (gpt_pro) model |
| `DANUS_CONSULT_CLAUDE_CODE_MODEL` | `claude-fable-5` | (claude_code) model via the `claude` CLI |
| `DANUS_CONSULT_CLAUDE_CODE_BIN` | `claude` | (claude_code) path to the CLI |
| `DANUS_CONSULT_CLAUDE_CODE_MAX_WALL` | `1800` | (claude_code) hard wall-clock cap per consult (s) |
| `DANUS_CONSULT_CLAUDE_CODE_PRICE_IN` | `10.0` | (claude_code) ledger estimate, USD per 1M input tokens |
| `DANUS_CONSULT_CLAUDE_CODE_PRICE_OUT` | `50.0` | (claude_code) ledger estimate, USD per 1M output tokens |
| `DANUS_CONSULT_CLAUDE_API_KEY` | — (falls back to `ANTHROPIC_API_KEY`) | (claude_api) BYO Anthropic API key |
| `DANUS_CONSULT_CLAUDE_API_BASE_URL` | Anthropic default | (claude_api) only for a proxy |
| `DANUS_CONSULT_CLAUDE_API_MODEL` | `claude-fable-5` | (claude_api) any Claude model |
| `DANUS_CONSULT_CLAUDE_API_FALLBACK` | `claude-opus-4-8` | (claude_api) refusal-fallback model; `off` disables |
| `DANUS_CONSULT_CLAUDE_API_PRICE_IN` | `10.0` | (claude_api) USD per 1M input tokens (real usage) |
| `DANUS_CONSULT_CLAUDE_API_PRICE_OUT` | `50.0` | (claude_api) USD per 1M output tokens (real usage) |

- `gpt_pro` = a paid, per-token OpenAI-compatible model. `claude_api` = the
  Anthropic API via the native SDK (per-token, BYO key; cost from real usage).
  `claude_code` = your Claude subscription via the Claude Code CLI (`claude -p`).
  `off` = the main agent reasons on its own, no consult.
- The `claude_code` consult runs **isolated**: a throwaway cwd, no settings and no MCP
  servers loaded (`--setting-sources "" --strict-mcp-config` — needs a recent
  `claude` CLI), web-only tools, and the prompt on stdin (never argv, which is
  world-readable on a shared host). It sees the elaboration and the public web,
  nothing else.

## Models & reasoning effort

All three codex-exec sites (workers, verifier, paper/report renderers) resolve
binary + model + effort through the shared launcher, so names are unified. Neutral
defaults apply everywhere; per-service overrides win.

| variable | default | applies to |
|---|---|---|
| `DANUS_CODEX_BIN` | `<repo>/bin/codex`, else `codex` on PATH | all codex calls |
| `DANUS_CODEX_MODEL` | `gpt-5.5` | neutral default (all sites) |
| `DANUS_CODEX_EFFORT` | `xhigh` | neutral default effort (all sites) |
| `DANUS_VERIFY_MODEL` / `_EFFORT` | neutral | verifier — the correctness authority; keep effort at `xhigh` |
| `DANUS_WRITE_PAPER_MODEL` / `_EFFORT` | neutral | paper renderer |
| `DANUS_HUMAN_SUMMARY_MODEL` / `_EFFORT` | neutral | human-summary renderer |

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
