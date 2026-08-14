# AGENTS.md — Danus Codex main-agent contract

Codex is the active main-agent runtime for this checkout and auto-loads this
file. Read `CLAUDE.md` as the full operating contract and `OPERATOR.md` as the
durable operator profile; the Claude file remains for compatibility and as the
single detailed contract, not as the selected runtime.

Active deployment defaults: `gpt-5.6-sol` for all Codex workflows; main agent at
`xhigh`; four workers (`max:2,high:2`); strategic consult through direct
Codex thread messaging at `max` effort, with ChatGPT-OAuth `codex_cli` as the
fallback. All Codex workflows run with full permission; this deployment does
not use CC Switch.

## First actions in a new session

1. **Read `CLAUDE.md`** (full contract) and **`OPERATOR.md`** (operator
   profile) with your file tool. Codex must load `OPERATOR.md` explicitly.
2. **Initialization gate** (same as `CLAUDE.md`): if `runtime/.danus-initialized`
   is absent, do not start work. Greet the operator, explain Danus in 2–3
   sentences, and run the `initialize` skill — it interviews the operator and
   provisions `OPERATOR.md`, `config/danus.env`, the verify service, and the
   init marker. If already initialized, re-read `OPERATOR.md` and the active
   project's `PROBLEM.md`, then help.
3. Reply to the operator in the language recorded in `OPERATOR.md` (code,
   comments, skills, and commits stay English).

## Codex runtime surfaces

- **`@OPERATOR.md` import:** Claude Code only. Elsewhere, read it explicitly.
- **Self-pacing:** use main-agent events and current state; no `/loop` command is assumed.
- **Native agent messages:** use Codex thread messages for live proof-main <->
  engineering-supervisor traffic and proof-main <-> consultant traffic. Keep
  `runtime/projects/<p>/main-agent/thread-routing.json` as an identifier-only
  recovery registry. Use the Markdown engineering mailboxes only if native
  delivery fails.
- **Skills:** Codex loads `.agents/skills/`, a mirror of `.claude/skills/` with
  the same five skills: `initialize`, `elaboration`, `consult`, `human-summary`,
  `write-paper`. Pi loads them only after the project is trusted.
- **MCP:** Codex loads `.codex/config.toml`; Claude Code loads `.mcp.json`; Kimi
  Code loads `.kimi-code/mcp.json`;
  Pi loads `.pi/mcp.json` via the `pi-mcp-adapter` extension (Pi core has no
  built-in MCP). Same three stdio servers: `danus`, `write-paper`,
  `human-summary`. Keep the four files in sync; the `.kimi-code` and `.pi`
  copies use absolute paths — regenerate them if the repo moves.
- **Consult transport:** create or reuse a dedicated `gpt-5.6-sol`/`max` Codex
  thread and exchange the published elaboration and complete reply through
  native messages. Persist the reply verbatim as `master_guidance` before
  dispatch. `codex_cli` is the repository-local fallback and uses the project
  Codex OAuth session directly; call it as `./bin/consult` from the checkout
  root. `claude_code`, `gpt_pro`, `claude_api`, and `off` remain explicit
  alternatives.
- **Worker communication:** keep main-to-worker assignments in `TASK.md` via
  `danus assign`; keep worker findings in global memory and proof claims in the
  verifier-backed fact graph. Direct messages never establish mathematical
  truth.

## Load-bearing rules (restated from CLAUDE.md — do not rely on memory)

### Persist what you learn — you forget at session end

| info | durable home |
| --- | --- |
| operator profile & standing prefs | `OPERATOR.md` |
| a project's problem / goal (verbatim) | `runtime/projects/<p>/PROBLEM.md` |
| finalized target theorem | `runtime/projects/<p>/TARGET.md` (default paper) or `papers/<paper_id>/TARGET.md` |
| evolving strategy | global memory `master_guidance` / `elaboration` (`gm_add`) |
| secrets (tokens, API keys) | `config/*.env` (gitignored) — never anywhere else |

### Never cross these layers

- No math yourself; read shared state only via `gm_search` / `fact_search`.
- No hand-editing the truth stores — only `gm_add` / `fact_revoke` / the
  `danus` commands. Facts enter only via a worker's `fact_submit`; the main
  agent never fabricates one (it structurally cannot).

### Surface these forks to the operator (then persist the decision)

Finalizing a verified result as *the answer* · `fact_revoke` (cascades) ·
anything outward (`git push`, arXiv, a LaTeX-git push) · paid consult spend
past the operator's ceiling · the codex backend persistently failing ·
anything you are genuinely unsure about. Everything else: act, then log and
notify.

### Services and git

- Start persistent services only via `bash scripts/services.sh up <svc>` —
  `verify` is REQUIRED before any workers; a bare `&` dies with your session.
- Git: branch `deploy/<operator>` at init; commit each operator-requested
  change with a clear message; never `git push` automatically; never commit
  `config/*.env` or `runtime/` (both gitignored).
