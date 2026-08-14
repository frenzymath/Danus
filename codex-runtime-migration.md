# Codex Runtime Migration

## Outcome

- Main-agent runtime: Codex with model `gpt-5.6-sol` at `xhigh`, following upstream commit `7a51336` and the
  `upstream/codex` / `v0.1.0-codex` layout.
- Project MCP surface: `danus`, `write-paper`, and `human-summary` in
  `.codex/config.toml`.
- Default and active worker roster: `max:2,high:2` (`max`, `max2`, `high`,
  `high2`), all on `gpt-5.6-sol`.
- Strategic consult: native `codex_cli` transport, direct ChatGPT OAuth with no
  CC Switch/API proxy, model `gpt-5.6-sol`, default effort `max`.
- Permissions: main, workers, verifier, consultation, and artifact renderers all
  use Codex full-permission mode.
- Proof ownership after acceptance: a fresh resident Codex session receives only
  the proof handoff. Engineering blockers are routed to the supervising session
  through `runtime/projects/w1-slab/main-agent/ENGINEERING-QUESTIONS.md` and
  `ENGINEERING-ANSWERS.md`.

## Runtime migration

- `.codex/config.toml`: replaced the absolute one-server draft with the portable
  upstream three-server configuration and 3600-second tool timeouts.
- `examples/ops/main-agent-tmux.sh`: launches
  Codex from the repository root with the resolved `DANUS_CODEX_MODEL` and
  `DANUS_CODEX_EFFORT` (or `DANUS_MAIN_MODEL` / `DANUS_MAIN_EFFORT` overrides),
  plus autonomous permissions. Explicit model selection makes the project
  contract independent of user-level defaults.
- `AGENTS.md`: identifies Codex as the active main runtime and points to the full
  compatibility contract plus the Codex MCP/skill surfaces.
- User-facing docs and role contracts now describe the selected Codex runtime.
- `scripts/setup-codex.sh chatgpt` now writes a direct OAuth config with no
  `base_url`, provider, API key, or proxy token. It persists the resolved Danus
  default `model` and main-agent `model_reasoning_effort` at the top level of
  `$CODEX_HOME/config.toml`, plus `approval_policy=never`,
  `sandbox_mode=danger-full-access`, and a trusted repository root, so
  a plain Codex TUI always starts as Sol/xhigh with full permission.

## Roster migration

- Code and CLI default changed from `high:3,xhigh:4` to `max:2,high:2`.
- `runtime/projects/w1-slab/project.json` now declares four workers.
- Six stopped worker homes were moved intact, not deleted, to:
  `runtime/projects/w1-slab/retired-workers/2026-08-13-roster-max2-high2/`.

## Consult migration

- Package default model: `gpt-5.6-sol`.
- `DANUS_CONSULT_EFFORT` is now a persistent deployment setting; its fallback is
  `max`, while explicit `--effort` still wins.
- Live ignored config resolves to `codex_cli / gpt-5.6-sol / max` through direct
  ChatGPT OAuth. API endpoint/key overrides are scrubbed from the consult child;
  no credential values were printed or committed.
- The consult skill no longer recommends Kimi/DeepSeek for this deployment.

## Verification

- `git diff --check`: passed.
- `bash -n examples/ops/main-agent-tmux.sh`: passed.
- Execution standalone tests: all passed.
- Orchestration CLI standalone tests: all passed.
- Strategy standalone tests: 45 passed; 3 fixture-only tests were explicitly
  skipped by the repository runner.
- The runtime venv has no `pytest` module, so the combined pytest command could
  not run; this changed no state.
- `codex mcp list`: all three project servers enabled.
- Live MCP handshake/list-tools:
  - `danus`: 5 tools;
  - `write-paper`: 6 tools;
  - `human-summary`: 1 tool.
- Consult resolution probe: transport `codex_cli`, model `gpt-5.6-sol`, effort
  `max`, direct OAuth active.
- `danus list/status`: `w1-slab` has exactly four workers, initially 0 live.
- Verify and `dashboard-w1-slab` services: up.

## Preserved scope

- No worker history was deleted.
- No secrets were exposed or added to tracked configuration.
- Existing human-summary, report-writer, Codex-provider, setup-script, Kimi, Pi,
  and unrelated dirty-worktree changes were preserved.
- No commit and no push were performed.
