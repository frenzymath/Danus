---
name: consult
description: Consult a strong reasoning model for strategy — feed it the current elaboration, take its reply as the next master_guidance, and dispatch workers from it. This is the main agent's high-intelligence step (workers prove; the consult decomposes and steers). Runs over the gpt_pro transport (a paid API, default), the claude_api transport (the Anthropic API, per-token BYO key), or the claude_code transport (your Claude subscription); if no key/login is configured it degrades to off, where the main agent reasons on its own. Use it each strategic cycle, on events (a worker finished a round / real new progress), not a blind timer.
---

# Consult for strategy

You are the **main agent**. Workers do the proving; **you do the high-level
thinking by consulting a strong reasoning model and turning its reply into
dispatch.** This is the strategic core of the loop: distil state (the
`elaboration` skill) → consult → record the reply as `master_guidance` → assign
workers from it.

The consult is the **core direction-guidance mechanism** — it is how the swarm
gets steered — and the **only step that costs money** (codex workers + the verify
service are free). Treat it as central, not optional.

## When to consult (events, not a timer)

The gate is **judgment about new state**, not the clock. Consult only when there
is genuinely new state to reason over:

- a worker **finished a round** and produced real new state;
- a **substantive new finding / dead end / verified fact** changed the picture;
- the swarm is **stuck** and needs a new direction.

Do **not** re-consult when nothing material has changed since the last
`master_guidance`. A sensible cadence is **at most once every ~2 hours** — a
consult itself takes minutes, and you want real state to reason over, not churn.
Drive cadence off main-agent events (or your own `/loop`), never a blind timer.

**Spend discipline.** Each API consult costs money and accrues to the project's
running total. Prefer `--effort high` (the workhorse); reserve `xhigh` for genuine
forks. As project spend approaches the operator's ceiling, **surface it — that is a
load-bearing fork** (see the main-agent contract).

**Project start (no record, no direction yet):** do not launch blind. First
**discuss the problem with both the model AND the human**, get direction from both
sides, then start the workers.

## How to consult

1. **Prepare the elaboration first** (the `elaboration` skill): read global memory
   + the fact graph (never worker local memory), produce the five-section
   synthesis, and publish it with `gm_add` (kind `elaboration`). That published
   document is the consult prompt — never consult on an empty or stale prompt.

2. **Call the consult CLI** with the elaboration as input:

   ```bash
   consult --file <elaboration.md> --project <project_dir> --out <reply.md>
   ```

   - `consult` is the wrapper on PATH — it sources the deployment env and execs
     the strategy consult CLI (in `danus/strategy`) with the right Python.
   - **Transport** comes from config (`DANUS_CONSULT_TRANSPORT`, default `gpt_pro`); a
     per-call override is `--transport gpt_pro|claude_api|claude_code|off`. `gpt_pro`
     runs the paid OpenAI-compatible endpoint; `claude_api` runs the native Anthropic
     API (per-token, BYO key); `claude_code` runs the consult through the Claude Code
     CLI (`claude -p`); `off` short-circuits (see the `off` path below).
   - **Effort** (`--effort high|xhigh`, default `high`): `high` is the workhorse,
     `xhigh` for the hardest forks.
   - `--project` records the spend: one line per call appended to
     `<project_dir>/spend/consult.jsonl`, and the CLI returns the running
     `project_total_usd`. **Always pass `--project`.**
   - It prints a one-line JSON envelope (`transport`, `reply`, `usage.input` /
     `usage.output` / `usage.reasoning`, `cost_usd`, `seconds`, `project_total_usd`)
     and, with `--out`, writes the full reply as markdown. Field shapes and pricing
     are owned by `danus/strategy` — read them there; do not re-derive them here.
   - It is a **stateless gateway**: prompt in, reply out. It does **not** write the
     stores — you do, in the next step.

3. **Record the reply as `master_guidance`, VERBATIM.** Take the reply as the
   direction and publish it unedited:

   ```
   gm_add(kind="master_guidance", claim=<one-line gist of the direction>,
          evidence=<the full, unedited reply>,
          links={"elaboration_id": <the gm_add id from step 1>},
          input_tokens=<usage.input>, output_tokens=<usage.output>, cost_usd=<cost_usd>)
   ```

   The call's `input_tokens` / `output_tokens` / `cost_usd` from the envelope ride
   as extra fields, so each consult's cost sits next to what it bought. The
   `master_guidance` schema (field names, `verifiable=false`) is owned by
   `danus/core` (`DATA_MODEL.md`) — honor it, don't re-specify it.

   `master_guidance` is **strategy, not truth**: it is `verifiable=false`. Workers
   heed it each round for awareness, but it is **never a correctness source** — only
   the fact graph is. Do not edit the reply into your own opinion; **dispatch is
   where your judgment enters.** Wrong guidance is simply superseded by the next
   consult — **never `fact_revoke` it** (revoke cascades on *facts* only).

4. **Dispatch from it** (see the main-agent contract's command surface). If the
   reply names **distinct branches/directions**, put **different workers on
   different directions** by writing each a `TASK.md` with `danus assign`; if there
   are **fewer branches than workers**, multiple workers on one subgoal is fine.

5. **Keep the human informed** at the right severity (the elaboration + the
   consulted direction is what you summarize up, in the operator's language per
   `OPERATOR.md`). Surface the load-bearing forks (finalizing a result,
   cascade-revoke, posting outward, over-ceiling spend).

## The `off` path (no-key degrade — not the norm)

The strong-model consult is core. When `DANUS_CONSULT_TRANSPORT=off` (e.g. no key is
configured, or the operator disabled it), the consult short-circuits and this skill
degrades: **the main agent reasons on its own** from the elaboration, then records
that reasoning as `master_guidance` (step 3) with `cost_usd=0` and **explicitly
flagged as self-authored** — never fabricated from thin air. Everything else
(events-not-timer, verbatim recording of what you decided, dispatch, human
updates) is unchanged. This is a real fallback mode, not the default.

## Totaling spend

The consult meters its own spend; codex workers and the verify service run
separately on the operator's own codex backend. **Every** transport meters it:
`gpt_pro`, `claude_api`, and `claude_code` each compute `cost_usd = input/output
tokens × per-1M rate` (`gpt_pro`: `DANUS_CONSULT_PRICE_IN`/`_OUT`; `claude_api`:
`DANUS_CONSULT_CLAUDE_API_PRICE_IN`/`_OUT`, from the response's REAL usage; `claude_code`:
`DANUS_CONSULT_CLAUDE_CODE_PRICE_IN`/`_OUT`
— set these to your real model/plan rate; `off` is the only $0 transport). So
**project spend = the sum of `cost_usd` over consult calls**, recorded in two places:

- the **spend ledger** `<project>/spend/consult.jsonl` — one line per call
  (model / effort / transport-attempt / tokens / `cost_usd`), written by
  `--project`; the CLI also returns the running `project_total_usd`.
- the **`master_guidance` entries** in global memory — each carries its call's
  `input_tokens` / `output_tokens` / `cost_usd`.

**How you (main agent) check spend:** read `project_total_usd` from each consult's
envelope (or sum `cost_usd` over `<project>/spend/consult.jsonl`). Report the
running total in your `spend` summary and warn the operator as it approaches their
ceiling. The rates live in config (a rate change touches one env pair, not code).

## Discipline

The load-bearing rules are stated where they apply above (verbatim recording,
events-not-a-timer, cost on every call, guidance-is-never-truth). Two more that
belong nowhere else:

- **One main agent at a time** owns `master_guidance` — do not race two.
- **Setup:** the `gpt_pro` transport needs an OpenAI-compatible endpoint + key, and
  `claude_api` an Anthropic key (both BYO, in `config/danus.env` via the
  `DANUS_CONSULT_*` vars); `off` is a no-key degrade. If the
  key/quota is exhausted, that is an operator fork, not something to work around.
