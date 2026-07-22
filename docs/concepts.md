# Danus — Concepts

A human's mental model of Danus: the actors, the memory layers, the one truth
boundary, and the lifecycle of a project. Read this before the operating guide.
For the design map and module index see `../ARCHITECTURE.md`; for the trust model
see `security-and-trust.md`.

## What Danus is

Danus is an **automated mathematics proof-search system**. You give it a problem;
a swarm of autonomous agents tries to prove it; every claimed result is checked by
a single correctness authority; verified results accumulate in a shared graph; and
when you decide the answer is in hand, Danus renders it into a human progress
report or a publishable LaTeX paper.

The defining idea is a **hard separation between *producing* mathematics and
*deciding it is correct***. Many agents produce; exactly one authority (the
verifier) decides; and a result only *exists* once that authority has accepted it.

## The actors

- **You, the operator.** You pose the problem, make the judgment calls Danus
  surfaces (is this the answer? push the paper outward?), and set the spending and
  operating preferences. You talk to Danus in natural language through the main
  agent.
- **The main agent (Claude Code).** The orchestrator and your entry point. It
  **steers — it does not do the mathematics.** It sets up projects, runs the
  strategy loop, assigns work, monitors, and drives the report/paper skills. It
  *structurally cannot* fabricate a result (it has no `fact_submit` tool).
- **The codex workers.** A swarm of autonomous `codex` sessions that actually
  prove lemmas. Each runs a round loop: it reads its assignment and the shared
  state, picks proving skills, works, and submits results for verification. Workers
  run detached and resume from persisted memory, so no single crash loses verified
  work.
- **The verifier.** A **cold-start** `codex` judge, started fresh for each check,
  that is the **sole authority on correctness**. A result becomes a fact **if and
  only if** the verifier returns a `correct` verdict. It is an LLM, not a formal
  proof assistant — see `security-and-trust.md`.
- **The strategy consult.** The main agent's high-intelligence step: it distills
  the project's state (an *elaboration*) and consults a strong reasoning model,
  whose reply becomes the swarm's steering (`master_guidance`).

## The three memory tiers, and the one truth boundary

Everything a project knows lives in three tiers that differ by **scope** and
**trust**:

| tier | scope | holds | is it truth? |
|---|---|---|---|
| **local memory** | one worker, private | that worker's rough notes / actions | no — private scratch |
| **global memory** | project-shared | typed *findings*: a claim + its evidence, including dead ends | no — shared awareness |
| **fact graph** | project-shared | verified facts | **yes — the only correctness source** |

A finding flows left to right, getting more structured and more trusted: a private
note becomes a shared finding (`global memory`), and a *verifiable* finding that
the verifier accepts becomes a **fact**. Crucially:

- **Only the fact graph is truth.** Global memory — even a plausible, not-yet-checked
  claim — is awareness only. A proof may build **only** on facts (by citing their
  ids), never on unverified findings.
- **There is no promotion shortcut.** Nothing "promotes" a claim to a fact except a
  worker submitting it and the verifier accepting it.

## The fact graph

The fact graph is the crown jewel. Each **fact** is one node — a human-readable file
with a statement, a proof, optional intuition, the ids of the facts it depends on
(`predecessors`), the symbols it defines (`glossary_introduces`), and its external
citations (`external_refs`).

- **Content-addressed.** A fact's id is a hash of its mathematical content
  (problem + predecessors + glossary + statement + proof). Same content ⇒ same id
  ⇒ natural dedup and stable references. `external_refs` is deliberately **excluded**
  from the hash, so the paper pipeline can correct citations later without breaking
  the graph.
- **A DAG.** `predecessors` are the edges; content-addressing forbids cycles.
- **Cascade-revocable.** Revoking a fact also revokes everything that transitively
  depended on it, and a proof can never build on a revoked predecessor.
- **Self-contained.** A lightweight glossary check keeps every fact readable — no
  fact silently uses an undefined symbol.

For the on-disk shapes and exact fields, see `../danus/core/DATA_MODEL.md`.

## The strategy loop (how the swarm is steered)

The main agent does not micro-manage proofs; it steers, periodically, on genuine
new state:

1. **Elaborate** — distill the shared stores into a high-signal synthesis (verdict,
   closed routes, interfaces, dangers, missing bridge lemmas). *(the `elaboration`
   skill)*
2. **Consult** — send that synthesis to a strong reasoning model. *(the
   `consult` skill)*
3. **Record & dispatch** — store the reply verbatim as `master_guidance` and give
   each worker its per-round assignment (`danus assign`).
4. **Monitor** — watch progress; repeat when there is genuinely new state.

The consult transport is configurable: **`gpt_pro`** (a paid OpenAI-compatible
model, the default), **`claude_api`** (the Anthropic API, per-token BYO key),
**`claude_code`** (your Claude subscription via the Claude Code CLI), or **`off`** (the
main agent reasons on its own, no spend). Workers and the verifier always run on
your own codex backend.

## The lifecycle of a project

```
initialize ─▶ new project ─▶ strategy loop ⇄ worker swarm ─▶ verify ─▶ fact graph
   (setup)     (PROBLEM.md)   (elaborate→consult→assign→monitor)   (the write-gate)
                                     │                                  │
                              human-summary                  finalize (you confirm
                    (progress report — any time, no gate)        the answer)
                                                                        ▼
                                                                   write-paper
                                                               (publishable LaTeX)
```

- **initialize** — first-run setup: your profile, the codex backend, the consult
  transport, the git branch, the spend ceiling; brings the verify service up.
- **new** — create a project (`PROBLEM.md` + a worker roster). One project = one
  problem, its own memory and fact graph.
- **strategy ⇄ workers** — the loop above; workers prove, submit, and the fact
  graph grows.
- **verify** — every submission passes through the verifier; a fact is written only
  on `correct`.
- **human-summary** — a private PDF progress report rendered from the verified
  results; run it at **any time** during the run (it is not gated on finalize).
- **finalize** — *you* decide a verified fact is the answer (`danus finalize`).
  Danus does not decide "done" on its own — that judgment is surfaced to you. (When
  the main agent judges every target proved, it does stop the swarm's exploration on
  its own to save compute, then asks you to confirm the answer; `danus start`
  resumes exploration if you disagree.)
- **write-paper** — after finalize: render the target's verified facts into a
  publishable paper, re-verified as written — the whole document, through a
  dedicated paper-math verifier — before delivery.

## Why you can trust the shape

Every guarantee above — one correctness boundary, permission by construction, the
verifier as the sole write-gate, resumable workers, the judgment calls staying with
you — is enforced in code, not by prompt convention. For exactly what you are
trusting (and what to double-check), read `security-and-trust.md`; the full
engineering invariant list is `../ARCHITECTURE.md` §3.

## Where to go next

- **Set it up and run it:** `getting-started.md`, then `operating-guide.md`.
- **What can I run / call:** `cli-and-tools.md`.
- **What am I trusting:** `security-and-trust.md` (read this before relying on a
  result).
- **Design & module map:** `../ARCHITECTURE.md`; data shapes:
  `../danus/core/DATA_MODEL.md`.
