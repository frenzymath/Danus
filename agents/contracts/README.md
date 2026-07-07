# contracts/ — agent root contracts

The standing system prompt each agent **tier** reads at the top of every session —
the binding operating protocol, distinct from the on-demand skills under
`agents/skills/`. These are data (markdown), not code.

| File | Tier | Reads / writes |
| --- | --- | --- |
| `main_agent.md` | main agent (Claude Code) | reads global memory + fact graph; writes `master_guidance` / `elaboration` (`gm_add`); `fact_revoke`; high-autonomy orchestration. NO `fact_submit`. |
| `worker.md` | codex worker | local memory (private) · global memory (`gm_add` / `gm_search`) · fact graph (`fact_submit`); the adaptive proving loop. Loaded per round via the worker home's `AGENTS.md` symlink. |
| `verifier.md` | codex verifier (verify service) | judges `{statement, proof}` → strict verdict; called by `fact_submit`; read-only (only `search_arxiv_theorems`); writes its verdict JSON directly to results/{run_id}/verification.json. |

Claude Code, the primary main agent, also auto-loads its condensed contract from
the repo-root `CLAUDE.md`; `main_agent.md` is the full contract and single source
of truth (the two must not contradict).

## The shared spine

Consistent across all three tiers:

- **The fact graph is the one source of truth** — a content-addressed DAG of
  verifier-accepted facts.
- **A fact enters only through `fact_submit`** (verifier-gated).
- **The verifier is the sole authority on correctness** — `correct` iff zero
  `critical_errors` AND zero `gaps`; no peer/LLM opinion substitutes.
- **Global memory** (incl. `master_guidance`) is shared awareness/strategy, never
  a correctness source — a proof builds only on `fact_id`s.
- **The shared stores change only through the sanctioned MCP tools**, never by hand.

## Who binds to these files

- `danus/gateway` — the exact MCP tool set + role gating (`main` has no
  `fact_submit`; `worker` adds it; `verifier` is read-only (`search_arxiv_theorems` only)).
- `danus/core` — the three-memory data model, the global-memory `kind`s, `fact_id`,
  the global glossary. The contracts are the human-readable statement of that model.
- `danus/verify` — `verifier.md` **is** the verify service's system prompt; its
  P1/P3/P5/P6 prohibitions pair with the server's single-line prechecks (and are
  the sole enforcement wherever those prechecks are off).
- `danus/execution` — loads `worker.md` per round (worker home `AGENTS.md`
  symlinks to `agents/contracts/worker.md`); the worker reads `TASK.md` +
  `master_guidance`.
- `agents/skills/worker` & `agents/skills/verify` — the contracts reference `$…`
  skills by name; the reconciliation note in `worker.md` tells inherited skills to
  defer to this data model.
