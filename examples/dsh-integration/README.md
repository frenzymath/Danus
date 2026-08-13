# Danus × DeepSeek Harness (dsh) integration

Three optional, composable seams — all ADD to Danus, none replace the existing
OpenAI/Anthropic paths (each is selected by config; defaults stay as before):

1. **MCP in the dsh web profile** — register the role-gated danus gateway (plus
   write-paper / human-summary) in a dsh profile so dsh sessions get the Danus
   orchestration tools (gm_add / gm_search / fact_search / fact_revoke /
   search_arxiv_theorems). Run `bash scripts/apply-dsh-mcp.sh` (backs up the
   current patch, writes the rows from `cordis.patch.yml.example`, validates
   the composed profile, handshake-probes all three MCP servers), then restart
   the dsh web server.
2. **dsh codex backend** — `CODEX_BACKEND=dsh` (config/danus.env) turns every
   `codex exec` (worker rounds, the verify service, paper/report renderers)
   into one `dsh --profile headless` session on DeepSeek models, via
   `bin/codex-dsh`. No OpenAI key needed. Requires
   `bash scripts/setup-dsh.sh` (installs @deepseek-ai/dsh under runtime/).
3. **dsh consult transport** — `DANUS_CONSULT_TRANSPORT=dsh` (or
   `consult --transport dsh`) runs the strategic consult as a headless dsh
   session instead of gpt-5.5-pro / Claude.

## Prerequisites

- `bash scripts/setup-dsh.sh` — provisions the dsh CLI into runtime/ and writes
  `DANUS_DSH_NODE` / `DANUS_DSH_BIN` to runtime/runtime.env (idempotent).
- DeepSeek credentials + the default model come from the deployment dsh home
  (`DANUS_DSH_HOME`, default `$HOME/.dsh` — the same home `dsh web` uses).
- Danus itself bootstrapped (`bash scripts/bootstrap.sh`) — the gateway MCPs
  need the venv / node toolchain.

## How the dsh backend maps `codex exec`

`danus.codex` is the single launcher (binary/model/effort/env/argv). With
`CODEX_BACKEND=dsh` it resolves `bin/codex-dsh`, which translates the uniform
`codex exec` argv into one `dsh --profile headless "<task>"` run:

- flags with no headless equivalent are dropped (`-C`, `-c`, `--sandbox`,
  `--skip-git-repo-check`, `--dangerously-bypass-approvals-and-sandbox`,
  `--config` toggles); the remaining positional (or stdin `-`) is the task;
- `--model` wins only when it names a deepseek-ish model; otherwise the dsh
  home's saved model wins (`DANUS_DSH_MODEL` overrides);
- effort maps onto DeepSeek's enum (off | high | max): minimal/low/medium ->
  high, high -> high, xhigh/max -> max (`DANUS_DSH_EFFORT` overrides; the line
  is only written when the deployment home already carries a reasoning tier);
- each run gets its own DSH_HOME under `$DANUS_RUNTIME/dsh-runs/` (credentials
  + settings copied from the deployment home) — headless sessions never touch
  the operator's web profile;
- the role-gated danus gateway is mounted as an mcp-client plugin in the
  per-run headless profile (role from `-c`; workers default to
  role=worker/author=<worker-dir-name>/project=<grandparent-of-cwd>, since the
  worker cwd is `<project>/workers/<name>`), so workers keep gm_add / gm_search /
  fact_submit / fact_search and the verifier keeps
  search_arxiv_theorems under the `mcp__danus__*` names;
- stdout = the session's final answer, exit code passes through;
- with the dsh backend the verifier's run dirs default under the verify agent
  home (the headless workspace); an explicit VERIFIER_RESULTS_DIR still wins.

Known backend differences (documented, not hidden): the dsh session's file
sandbox is its cwd, so the verify agent must write inside its home (handled by
the default above); the authoring reference-verify path has no codex web_search
tool (headless exposes its own `web_search`), and paper/report renderers run
the same self-contained prompts with headless's native tools.

## Consult transport

`DANUS_CONSULT_TRANSPORT=dsh` + `bash scripts/setup-dsh.sh`. Each consult is a
headless session in its own DSH_HOME under `$DANUS_RUNTIME/dsh-runs/`; the
envelope is the pinned uniform shape. headless reports no token usage, so
ledger metering is opt-in via `DANUS_CONSULT_DSH_PRICE_IN/_OUT` (char-based
estimate) — off by default (honest $0 rather than fabricated numbers).

## Tests

- `python3 -m danus.tests.test_codex` — backend selection + dsh prompt embedding
- `python3 -m danus.tests.test_codex_dsh` — the bin/codex-dsh translation shim
- `python3 -m danus.strategy.tests.test_dsh_transport` — the dsh consult transport
