---
name: elaboration
description: Write a high-signal mathematical synthesis from global memory and the fact graph for the Codex main agent's own strategy and worker dispatch.
---

# Elaboration

You are the **main agent**. At each strategic cycle, including the global review
on each roughly 30-minute heartbeat, you distill the project's current state into
one **elaboration** when the synthesis materially changes: a readable, deeply
analytical synthesis for your own reasoning and worker dispatch. The heartbeat
itself always requires a fresh global appraisal, but it need not create a
duplicate elaboration when nothing material changed. You may ask speculative
Codex subagents to explore individual gaps or undertake sustained technical
reasoning, but their reports remain unverified and must be labelled as
hypotheses. You author the next `master_guidance` yourself.

The elaboration is also what you draw on to keep the operator informed.

## Template invariants (validate every elaboration against these)

A well-formed elaboration satisfies all of the following — a worker or linter can
check them mechanically:

- **Five sections, in order, no dropped heading:** §0 Mathematical verdict · §1
  Closed components and obsolete routes · §2 Interface contract table · §3
  Dangerous heuristic lines and strategies not to pursue · §4 Missing bridge
  lemmas. An empty section is written as its honest empty-state line, never
  omitted.
- **The two fixed empty-state lines** (§1) are used verbatim when a subsection is
  empty:
  - `_(no signed-closed components yet)_`
  - `_(no failed or obsolete routes recorded; absence here does not mean the strategy is unique)_`
- **Exactly seven status labels**, UPPERCASE, drawn only from: **CLOSED ·
  SUBSTANTIAL · PARTIAL · DANGEROUS · FALSE AS STATED · OBSOLETE · UNKNOWN**.
- **§0 opens** with exactly one bolded verdict line and contains the status
  dashboard table + the sub-task status summary table + the approach portfolio +
  the Current best proof skeleton + the Central missing lemma.
- **Every `fact_id` cited exists** in the fact graph; no invented ids, no
  paraphrase substituted for a verified statement.
- **Published** via `gm_add(kind="elaboration", …)` with `verifiable` left at its
  default (`false`).

## Input Contract

Read **only the shared stores** — never a worker's private local memory (a layer
boundary, and the reason this is cleaner than a log-scraping summary agent). All
reads are project-scoped for the main agent (`project=<p>`):

- **global memory** — findings, dead ends, recent `verification` traces, the
  current `master_guidance`. Read via `gm_search`, or as a fallback by reading the
  raw `runtime/projects/<p>/global_memory/<kind>.jsonl` files.
- **fact graph** — the verified facts, their statements, and the DAG. Read via
  `fact_search`, or as a fallback by reading the raw
  `runtime/projects/<p>/fact_graph/facts/*.md` files: what is established vs. still
  open, and how facts compose.
- **the project's problem statement** — the fixed goal and, if present, its
  enumerated sub-tasks / intended proof architecture.

## The fixed goal is sacred

Quote the goal and **do not change or weaken it** — do not redefine, simplify,
restrict to a special case, or substitute an easier proxy. If the evidence
suggests the goal may be false or unreachable by the current strategy, **say so
plainly while keeping the goal fixed.**

## Template — five sections

Produce one markdown document with these sections, in order. Omit a section's
body only by writing the honest empty-state line, never by dropping the heading.

### 0. Mathematical verdict

Open with **one** of these, in bold on its own line:

> **Not solved.** … | **Counterexample found.** … | **Verified complete proof.** … | **Solved.** …

Then:

- **Closed components** — what is signed-closed today (1–2 sentences; cite `fact_id`s).
- **Viable proof architecture** — one sentence naming the current best route.
- **Main blocker** — what concretely blocks right now (1–2 sentences; cite `fact_id`s).
- **Highest-priority unresolved bridge** — the most leveraged missing lemma / integration package.
- **Method failure vs. proposition failure** — state explicitly whether the evidence indicates a *method* has failed (the conjecture may still hold) or the *proposition itself* may be false. Use the phrase "method failure" or "proposition failure" verbatim.
- **Calibration caveat** — one line warning the reader against over-reading status labels (e.g. "Do not read SUBSTANTIAL/CONDITIONAL as 'almost solved' — every such row has an unmatched hypothesis on the actual model.").

Then a **status dashboard** (one table) with at least these rows: Fixed goal
(UNCHANGED, with goal text); Verified complete proof (YES/NO); Verified
counterexample (YES/NO); Signed-closed sub-tasks (count + names); Main blocker
(a specific lemma, not vague); Routes marked false/obsolete (YES/NO + which);
Highest-priority unresolved task (P0/P1/P2 with the exact mathematical task).

Then a **sub-task status summary** (one table: Sub-task | Status | Closed facts |
Conditional facts | Main missing interface), one row per sub-task the problem
enumerates. Use **only** these UPPERCASE labels:

- **CLOSED** — verified on the *actual* construction, no remaining
  hypothesis-matching. A theorem import or conditional package being available is
  **not** CLOSED — that is SUBSTANTIAL. CLOSED is rare; default away from it.
- **SUBSTANTIAL** — a conditional package exists, but ≥1 input/output hypothesis
  is unmatched on the actual construction. The *default* for a sub-task with
  load-bearing tools not yet applied to the actual model.
- **PARTIAL** — isolated ingredients only; no coherent conditional package yet.
- **DANGEROUS** — a plausible shortcut that is false / insufficient / hypothesis-sensitive.
- **FALSE AS STATED** — a once-plausible formulation now refuted; do not pursue as stated.
- **OBSOLETE** — superseded by a better route; do not pursue.
- **UNKNOWN** — insufficient verified information.

> **Strict CLOSED test.** For each sub-task you are tempted to mark CLOSED, ask:
> "Is there a verified fact that handles this on the *actual* construction, with
> zero remaining hypothesis to match?" If you cannot answer YES with a specific
> `fact_id` and zero remaining work, mark SUBSTANTIAL. Over-marking CLOSED is the
> single most damaging error here — it reads as "no further work needed."

Then an **approach portfolio** (one table: Approach | Mechanism | Mathematical
frontier | Decisive obstacle | Evidence for/against | Active/parked | Revisit
condition). Include every credible route still worth remembering, not only the
currently dominant route. Preserve parked routes and their return conditions so
that recent work cannot silently erase a serious alternative. If a major route
choice has changed, state the alternatives considered and the mathematical
reason for the change; this decision must also be preserved in the subsequent
`master_guidance`.

End §0 with **Current best proof skeleton** (6–12 short numbered lines: the
smallest structure that closes the goal *if* the central missing lemma were
known, with `fact_id`s where facts apply) and **Central missing lemma** (the
single most precise unresolved statement, at full precision — all quantifiers,
definitions inlined for self-containment, and one short "why this is non-trivial"
paragraph if warranted).

### 1. Closed components and obsolete routes

- **Signed-closed components** — a bullet list ("<math content> — `fact_id`s
  `…`") or the line `_(no signed-closed components yet)_`.
- **Failed or obsolete routes** — a table (Route | FALSE AS STATED / OBSOLETE |
  one-line reason citing a `fact_id` / concrete obstruction), or
  `_(no failed or obsolete routes recorded; absence here does not mean the strategy is unique)_`.
  FALSE AS STATED = a plausible reduction now refuted; OBSOLETE = superseded by a
  simpler live route.

### 2. Interface contract table

The single most important diagnostic — a human reader uses it to find exactly
which input/output hypothesis is unmatched on the actual model. For **each**
interface in the proof architecture (use the exact sub-task names the problem
enumerates: per-stage A/B/C…, each transition B→C, C→D…, and the meta-reduction
to the original statement):

> ### \<Interface name\> — \<one-line role in the proof\>
> **Input required.** \<precise mathematical conditions step i+1 demands of step i's output — normality, Q-factoriality, R-Cartierness, dimension, …; not just "compatibility"\>
> **Output claimed.** \<what the existing conditional package guarantees, conditional on its own hypotheses\>
> **Available facts.** `fact_id` — one-line statement; …
> **Missing verification on the actual model.** \<numbered: the specific hypothesis-matches not yet carried out on the actual construction\>
> **Failure mode if ignored.** \<one or two sentences: what concretely breaks downstream — e.g. "If K_W+B_W is not Q-Cartier, 'by negativity lemma' is vacuous and the crepancy conclusion is unjustified."\>
> **Status.** \<one of the seven labels\>

Do not skip an interface even if its row is trivial — flag trivial matches so a
cold reader knows they were considered. Inline the definitions of load-bearing
terms so a cold reader need not consult the problem statement. If the problem is
built around a single central lemma rather than a pipeline, produce one interface
row for the central reduction in the same format. **Strict CLOSED rule applies
per row:** if "Missing verification" is non-empty, the status is SUBSTANTIAL or
weaker — never CLOSED.

### 3. Dangerous heuristic lines and strategies not to pursue

- **Dangerous heuristic lines** — 3–8 specific shortcut statements found
  **verbatim or in close paraphrase** in the problem's strategy outline or prior
  notes (preserve the wording so the reader can locate them). For each: a
  **Status** (one of: "Not automatic" / "Mathematically incorrect as stated" /
  "Conditional only" / "Method shortcut, not a proof step" / "Conflated with a
  stronger claim") and one 2–4 sentence paragraph on the precise reason it is
  unjustified, citing `fact_id`s; give the correct rephrasing where one is needed.
- **Strategies not to pursue** — 4–8 one-line anti-routes, each concrete: "Do not
  \<specific action\>: \<one-line reason\>." Vague entries ("avoid weakness") are
  forbidden.

### 4. Missing bridge lemmas

Identify 2–4 **bridge lemmas** — concrete intermediate facts that, if proven,
would either prove the central missing lemma or unblock a specific interface row.
For each:

> ### Bridge k — \<short name\>
> **Target statement.** \<full, precise mathematical statement\>
> **Prerequisites.** \<conditions the inputs must satisfy for the statement to type-check\>
> **Existing facts to use.** `fact_id` — one-line claim; … (only ids that actually exist)
> **Missing checks.** \<numbered: the specific hypothesis-matches / sub-proofs still needed\>
> **Closure criterion.** \<one paragraph naming the exact proof obligation that closes this bridge\>

Order by **leverage**: Bridge 1 unblocks the most downstream / has the highest
payoff per unit effort. State for each whether it is independent
(parallelizable) or dependent — this is what lets you put different workers on
different bridges.

## Discipline (hard rules)

- **Do not treat conjectural material as verified** — a claim without a `fact_id`
  is awareness, not truth.
- **No numerical distance estimates.** Never "≈ 8–12 facts", "2–4 focused runs",
  "80% done". Distance is qualitative. Estimating a numeric distance is forbidden.
- **No process telemetry.** No worker counts, service state, mtimes, run
  scheduling — this is purely mathematical. Do not discuss how the elaboration
  was produced, scheduled, or delivered.
- **No agent-facing directives.** The elaboration is a synthesis, not a dispatch
  order. Use it afterward to author `master_guidance` and worker assignments.
- **Honest, not reassuring.** Surface hidden assumptions, possibly-false
  statements, and places where a status label may mislead. Do not round
  SUBSTANTIAL up to "almost done".
- **Global, not locally captive.** Judge the whole portfolio and the route to the
  fixed goal. Fact volume, proof length, and activity inside the primary route do
  not by themselves show macro-level progress.
- **Literature-aware.** Before presenting a route as novel or committing heavily
  to it, use `search_arxiv_theorems` broadly with varied formulations and
  technique names. Record a concise technique map in global memory: mechanisms,
  exact assumptions, limitations, relevant arXiv identifiers/results, and
  possible interfaces with this problem. Understand and adapt established
  strategies before inventing new machinery; literature notes are not facts.
- **Four-hour macro audit.** At least once every four hours of active work,
  explicitly reassess and record the full approach portfolio, mathematical
  frontier and obstacle of each route, evidence for/against it, worker allocation,
  and whether to continue, complement, park, or resume each route.

## Output Contract

Publish the elaboration to global memory with `gm_add`:

- `kind`: `elaboration`
- `claim`: the §0 verdict line (the bolded opener + the one-line main blocker)
- `evidence`: the full five-section markdown body
- `links`: `{"fact_ids": ["…", "…"]}` — the facts you cited (only ids that exist
  in the fact graph)
- (`verifiable` defaults to `false` for this kind — it is a synthesis/judgment,
  not an objectively checkable claim; leave it unset.)

Then reason over the elaboration yourself. Optionally give precise pieces to
exploratory subagents, label their reports unverified, synthesize the result into
`master_guidance`, and dispatch Danus workers afterward.

## Tools

Reference the role=main MCP tools by name (never internal engine paths):

- `gm_search` / read `runtime/projects/<p>/global_memory/<kind>.jsonl` — gather
  findings, dead ends, recent verifications, current `master_guidance`.
- `fact_search` / read `runtime/projects/<p>/fact_graph/facts/*.md` — the verified
  facts and the DAG (`fact_search` to pull the facts bearing on a sub-task; read
  the files for the full statements/proofs and predecessor structure).
- `gm_add` (kind `elaboration`) — publish the synthesis.
- `search_arxiv_theorems` — use repeatedly with varied formulations and technique
  names to map the relevant literature, understand established mechanisms and
  hypotheses, and check whether missing bridges or nearby results already exist.
