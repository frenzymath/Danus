# Danus — Getting Started

Provision a self-contained Danus deployment and bring it to a healthy, ready-to-run
state. Read `concepts.md` first for the mental model; after this, see
`operating-guide.md` to run your first project.

## Prerequisites (on the host)

- **Linux** host you are willing to let autonomous agents operate on (a dedicated
  VM / container / pod — see `security-and-trust.md`).
- `git`, `python3` (3.10+), `curl`, `tar`, `bash`. `bootstrap.sh` provisions
  everything else (Node, a venv, the codex CLI) into `runtime/` — no system-wide
  installs.
- A **codex backend**: either an OpenAI-compatible API key, or a ChatGPT Pro/Plus
  subscription. This is what workers and the verifier run on (bring your own).
- *(Only for `write-paper`)* a LaTeX engine on `PATH` (`pdflatex`, or `tectonic` via
  `scripts/install-tex.sh`). Not needed for proving.

## 1. Provision the runtime

```bash
bash scripts/bootstrap.sh
```

Idempotent. Installs into gitignored `runtime/`:
- Node 22 → `runtime/node22` (default `NODE_VERSION` `v22.14.0`),
- a Python venv → `runtime/venv` (`mcp`, `fastapi`, `uvicorn`, `pydantic`, `openai`,
  plus the `danus` package itself as an editable install — the worker MCP gateway
  and the `bin/` wrappers run `python -m danus.*` from arbitrary cwds, so the
  package must be on the venv's path; the script validates the venv actually
  imports everything and rebuilds if the base interpreter went dangling),
- the codex CLI → `runtime/codex-npm` (`npm @openai/codex`),
- human-summary node deps (`markdown-it`/`katex`, soft — only for PDF rendering),
- `runtime/runtime.env` (machine paths that `scripts/env.sh` reads).

If `config/codex.env` already holds a real (non-placeholder) API key, bootstrap
also writes the codex `model_provider` for you.

## 2. Configure (copy the templates; fill YOUR values)

Secrets live **only** in these gitignored files (never committed):

```bash
cp config/danus.env.example config/danus.env    # host/account config (edit as needed)
cp config/codex.env.example config/codex.env     # BYO codex backend
```

Then pick your **codex backend** (workers + verifier):

- **API key (recommended, no login):** in `config/codex.env` set
  `CODEX_BACKEND=api`, `CODEX_API_BASE_URL=<your OpenAI-compatible endpoint>`,
  `CODEX_API_MODEL=gpt-5.6-sol`, `DANUS_CODEX_API_KEY=<your key>`. Then
  `bash scripts/setup-codex.sh api` (bootstrap already did this if the key was
  present) writes the provider — the key is read from the env var at run time, never
  stored in a config file.
- **ChatGPT subscription:** in `config/danus.env` set `CODEX_BACKEND=chatgpt`, then
  `bash scripts/setup-codex.sh login` and follow the device-auth flow.

The main agent steers the swarm by reasoning itself between rounds (optionally via
exploratory codex subagents) — there is no separate strategy transport or API key
to configure. See `configuration.md` for the full variable list.

## 3. Confirm the codex backend is reachable

```bash
bash scripts/check-codex.sh
```

It is **backend-aware**, exits `0` on success, and appends a trace line to
`runtime/logs/codex-health.jsonl`:
- **api** backend → makes one cheap live call to `CODEX_API_BASE_URL` (reads
  `DANUS_CODEX_API_KEY`) and scans recent logs; `ok codex API reachable`.
- **chatgpt** backend → there is no API endpoint to ping, so it probes the codex
  login instead and prints `ok codex backend: chatgpt login active (Logged in using
  ChatGPT)`.

## 4. Bring up the verify service (REQUIRED)

```bash
bash scripts/services.sh up verify
```

**Without the verify service, `fact_submit` fails and no facts are ever produced.**
`services.sh` `setsid`-detaches it so it survives your shell. See `operations.md`.

## 5. Health check

```bash
bash scripts/doctor.sh
```

Reports green / `FAIL` / `warn` across config, python + deps, node, the codex
wrapper + backend, a live verify `/health` probe, and soft checks for `pdflatex`
(write-paper) and Chrome/Chromium (human-summary PDF).

A real healthy run (chatgpt backend, no TeX installed — the `pdflatex` `warn` is a
soft, write-paper-only dependency):

```
== Danus doctor ==
DANUS_ROOT=/home/you/Danus
  ok   config/danus.env present
  ok   config/codex.env present
  ok   python: .../runtime/venv/bin/python
  ok   python dep: mcp
  ok   python pkg: danus (importable from any cwd)
  ok   python deps: fastapi/uvicorn/pydantic
  ok   node: .../runtime/node22/bin/node
  ok   codex: codex-cli 0.142.5
  ok   codex login ok (/home/you/codex-home)
  ok   verify service up :8091 (ours)
  warn no pdflatex on PATH (write-paper PDF render needs it; set TEX_ENGINE or install TeX)
  ok   chrome: /usr/bin/chromium-browser (human-summary PDF)
done.
```

On the **api** backend the two codex lines instead read `codex backend: api provider
configured` + `codex API live ping ok`.

## 6. Connect codex and initialize

Connect codex **rooted at this repo directory** (so `AGENTS.md`, `.codex/config.toml`,
and `.agents/skills/` load). On the **first** session, the main agent runs the
**`initialize`** skill: it interviews you (how to address you + language, git branch,
spend ceiling, codex backend), provisions `OPERATOR.md` +
`config/danus.env`, brings up verify, and writes `runtime/.danus-initialized`.

After initialize, continue with `operating-guide.md` to create and run a project.

## Troubleshooting

- Backend flaky? `bash scripts/check-codex.sh` (history in
  `runtime/logs/codex-health.jsonl`).
- Host restarted? `bash scripts/recover.sh` (see `operations.md`).
- Anything red in `doctor.sh` — fix it before starting workers.
