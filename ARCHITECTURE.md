# Danus — Architecture

Danus turns the Rethlas single-problem proof engine (a codex agent plus proving
skills, inherited rather than redesigned) into a multi-agent, long-running,
strategy-steered research system, and renders verified results into papers and
human progress reports. This is the as-built map: the layered model, the folder
layout, the invariants, and the pinned cross-module contracts.

For the main agent's operating contract, see `AGENTS.md`
(→ `agents/contracts/main_agent.md`).

---

## 1. Layered model

```
operator → ① orchestration (main agent + danus CLI)   — conducts, never does math
              ② strategy   (the main agent's own periodic synthesis: elaboration → master_guidance)
              ③ execution  (worker swarm; each round = one codex session running the Rethlas proving skills)
   gm_* │         │ fact_submit
        ▼         ▼
   ⑤ truth      ④ verification (cold-start codex judge; correct ⟺ no critical_errors AND no gaps)
   (fact graph + memory)   — a fact exists iff the verifier accepted it
        ▲
        │ every read/write goes through …
   ⑥ gateway (role-gated MCP: 6 tools; main has NO fact_submit; verifier read-only)

cross-cutting: ⑦ observability (dashboard · theorem-search · human-summary · initialize)
               ⑧ ops/runtime (bootstrap · services · doctor · config)
bottom (inherited, don't redesign): Rethlas proof core = codex + worker proving skills
output: write-paper (publication) · human-summary (progress report) — each rendered by an isolated codex
```

---

## 2. Folder layout

```
Danus/
├─ ARCHITECTURE.md              this file (map + invariants + interface contract)
├─ README.md   pyproject.toml   top-level intro + the installable `danus` package
├─ .gitignore  .codex/          MCP wiring (`config.toml`): the `danus` gateway + the `write-paper` and `human-summary` services
├─ config/                      env templates (standard Codex key; only *.env.example committed)
├─ danus/                       THE ENGINE (installable Python package)
│  ├─ core/                     ⑤ truth: schema · factgraph · global/local memory · bm25 · glossary
│  ├─ gateway/                  ⑥ role-gated MCP: 6 tools · role table (roles.py)
│  ├─ verify/                   ④ verification HTTP service · prechecks · cold-start codex launcher
│  ├─ execution/                ③ worker swarm: round loop · project/worker lifecycle + layout
│  ├─ orchestration/            ① the `danus` CLI verbs
│  ├─ integrations/             arXiv theorem search (Matlas)
│  ├─ observability/            read-only dashboard
│  ├─ authoring/                shared main-only renderer primitives: the one-shot isolated codex driver + common helpers
│  ├─ write_paper/              write-paper MCP service: assembler + tools (drives `danus.authoring`)
│  └─ human_summary/            human-summary MCP service: scrubbing assembler + tool (drives `danus.authoring`)
├─ agents/                      AGENT CONTRACTS + CODEX-FACING SKILLS (data, not Python)
│  ├─ contracts/                main_agent.md · worker.md · verifier.md
│  └─ skills/
│     ├─ worker/                9 proving skills (inherited from Rethlas)
│     ├─ verify/                3 verify skills
│     └─ write-paper/           paper role prompts + house style (embedded by the write-paper MCP)
├─ .agents/skills/              MAIN-AGENT SKILLS (codex auto-discovers)
│  ├─ elaboration/  human-summary/  initialize/
│  └─ write-paper/              the recipe SKILL.md + driver/ scripts + templates/
├─ bin/                         thin wrappers: danus · danus-mcp · write-paper-mcp · human-summary-mcp · codex
├─ scripts/                     bootstrap · doctor · services · env · check-codex · start-verify/-dashboard · recover · install-tex
├─ docs/                        human docs: getting started · concepts · operating guide · security & trust · …
└─ examples/                    unattended-ops examples + a toy project
```

---

## 3. Design invariants (must not regress)

1. Three memory tiers, one correctness boundary: local (private) → global
   (shared awareness) → fact graph (the only truth). A proof may build only on
   `fact_id`s; global memory is never a correctness source.
2. Permission is enforced by which tools a role can even see (the gateway role
   table), not by prompt convention. `main` cannot `fact_submit`; `verifier` is
   read-only.
3. The verifier is the sole write-gate. A fact exists only if a `correct` verdict
   came back; the gate lives in the `fact_submit` code path, not in prose.
4. Content-addressed, cascade-revocable fact graph. `fact_id` hashes content
   (problem_id + predecessors + glossary_introduces + statement + proof);
   `external_refs` is deliberately excluded so the paper pipeline can rewrite
   citations without breaking the DAG.
5. Autonomy and resumability. Workers run detached; a "round" continues from
   persisted memory rather than adding one increment, so no single crash loses
   verified work.
6. The main agent's own reasoning is the brain. Between rounds the main agent
   reasons over the shared stores itself — optionally spawning exploratory codex
   subagents — distills the project's state into an `elaboration`, and writes the
   direction it decides on as the swarm's `master_guidance`. This periodic steer
   is not optional — it is how the swarm gets steered.
7. Native Codex authentication. Danus does not construct model providers; Codex
   uses its stored ChatGPT login or the standard `CODEX_API_KEY`. No hardcoded
   absolute paths or committed secrets; keys live in gitignored `config/*.env`.
8. Clean author context. Any agent that produces an artifact for an outside
   audience (a paper, a human report) is a fresh isolated codex fed a scoped,
   machinery-free prompt, never the orchestrator's own contaminated window. It
   cannot leak `fact_id`s or swarm vocabulary it never received.

---

## 4. Interfaces & ports — the coordination contract

> **Rule:** these rows are the seams where two modules meet. If a change touches a
> row, update both ends in the same change. Ports and contract shapes are pinned:
> one side must treat the other's contract as fixed, and must not change a port or
> interface unilaterally.

**Network ports (loopback — do not renumber):**

| port | service | producer → consumer |
|---|---|---|
| 8091 | verify `/verify`, `/health` | `danus.gateway` `fact_submit` → `danus.verify` (via `DANUS_VERIFY_URL`) |
| 8099 | dashboard | operator browser → `danus.observability` (read-only) |

**Cross-module contracts (both ends must agree):**

| contract | pinned shape | ends |
|---|---|---|
| MCP tool set + role gating | 6 tools; `roles.py` `ROLE_TOOLS` (main has NO `fact_submit`; verifier read-only) | `danus.gateway` ↔ worker/main/verifier agents |
| MCP launch | `python -m danus.gateway` + `DANUS_ROLE` env | `danus.verify` launcher · worker `.codex/config.toml` · `.codex/config.toml` (main) → `danus.gateway` |
| verify HTTP | `POST /verify {statement,proof}` → `{verification_report,verdict,repair_hints}`; verdict ⟺ no critical_errors & no gaps | `danus.gateway.fact_submit` ↔ `danus.verify` |
| fact id inputs | `problem_id + sorted(predecessors) + sorted(glossary) + normalized(statement,proof)`; **external_refs EXCLUDED** | `danus.core` ↔ everyone (write-paper reads `external_refs`) |
| global-memory kinds | the 11 `GLOBAL_KINDS` (incl. `master_guidance`/`elaboration`/`verification`) | `danus.core` ↔ agents |
| write-paper prompt assets | codex role prompts + style read from `agents/skills/write-paper/` (via `DANUS_WRITE_PAPER_SKILL_DIR`) | `danus.write_paper` assembler ↔ `agents/skills/write-paper/` |
| env-var contract | `DANUS_* / CODEX_* / VERIFY_*` names; the codex CALL + env (bin/model/effort/PATH/`exec` prefix) is resolved through the shared `danus.codex` launcher: neutral `DANUS_CODEX_BIN` / `DANUS_MAIN_MODEL` / `DANUS_MAIN_EFFORT` (back-compat aliases `DANUS_CODEX_MODEL` / `DANUS_CODEX_EFFORT`) + `DANUS_WORKER_MODEL` for workers + per-service `DANUS_{VERIFY,WRITE_PAPER,HUMAN_SUMMARY}_{MODEL,EFFORT}` overrides | `danus.codex` + `config/` + `scripts/env.sh` ↔ every codex-exec site (`danus.execution.loop` · `danus.verify.launcher` · `danus.authoring.driver`) |
