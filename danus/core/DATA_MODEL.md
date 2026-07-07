# Danus core data model — local memory · global memory · fact graph

This is the **authoritative, detailed spec** of the three core data structures of
the Danus system, their relationships, and the logic for using them.
Skills, prompts, and the orchestration layer are written against this document —
read it before touching any of them.

> **The model, by scope.** Danus keeps one private per-worker running log and
> splits shared knowledge by **scope**:
>
> | name | scope | who reads it |
> | --- | --- | --- |
> | **local memory** | per-worker private | only that worker |
> | **global memory** | project-shared — the *categorized findings* | all workers + main agent |
> | **fact graph** | project-shared, verified | all workers + main agent |
>
> Strong **categorization** (typed channels) and the append-only JSONL + BM25
> mechanism live on the **global memory** layer (shared), because sharing typed
> findings — including dead ends — is the whole point. Per-worker `local memory`
> keeps only the rough "what I did" log. `fact_graph` is a content-addressed
> verified DAG.

---

## 0. The three tiers at a glance

```
                scope            structure          unit                 truth?
local memory    per-worker       loose / rough      "what I did" log     no  (private scratch)
global memory   project-shared   strongly typed     a CLAIM + evidence   no  (shared findings, incl. dead ends)
fact graph      project-shared   fully structured   a VERIFIED fact      YES (only correctness source)
```

A finding flows **left → right**, getting more structured and more trusted:

```
local memory  ──(worker auto-publishes a formed claim)──▶  global memory
global memory ──(verifiable=true → send to verifier → fix until correct)──▶  fact graph
```

**The load-bearing invariant:** a proof may only build on `fact graph` entries
(cite a `fact_id`). `global memory` is for **awareness** — dedup, ideas,
knowing which paths died — and is **never** a correctness source, even though it
holds claims with evidence. Only the verifier promotes a claim into the fact
graph. This is the same discipline as "peer-consult informs direction, the
verifier decides correctness."

---

## 1. local memory (per-worker private, rough)

**Purpose.** Each worker's private running log of what it thought and did, so it
can recall its own context later in the run. Deliberately rough — no schema
police. Other workers never read it.

**Scope.** Per-worker. Rooted at the worker's own directory.

**Storage.** `<worker_dir>/local_memory/<channel>.jsonl`, append-only JSONL,
BM25 recall. Default channels (small, can grow):

- `notes` — free-form thoughts, partial reasoning, things-to-try.
- `events` — a log of actions taken (searches run, skills invoked, a claim
  published to global memory, a fact submitted). Auto-logged + explicit.

**Entry envelope.**

```json
{ "timestamp_utc": "...", "channel": "notes", "record": { ...any JSON... } }
```

`record` is free-form — that is intentional; local memory holds "various
unformed content."

**Operations.** `append(channel, record)`, `search(query, channels, limit)`
(BM25), `read(channel)`.

**When a worker writes it.** Continuously, as it works — raw reasoning into
`notes`, actions into `events`. The moment a thought becomes a *formed claim*
(a conclusion, an example, a counterexample, a dead end, a direction), the
worker **auto-publishes** it to **global memory** instead (see §2). Local memory
keeps only the process, not the shareable findings.

---

## 2. global memory (project-shared, strongly typed findings)

**Purpose.** The shared pool of *findings* — every formed claim plus its
supporting evidence, **including dead ends** — so workers learn from each other
(don't re-walk a dead path, build on each other's ideas) and so verifiable
claims get driven toward the fact graph. Failures are shared, not locked in each
worker's private memory where only successes surface.

**Scope.** Project-shared. Rooted at the project directory; all workers and the
main agent read/write it.

**Storage.** `<project_dir>/global_memory/<kind>.jsonl` — **one append-only
JSONL file per kind** (one file per channel, shared) + BM25.
Status transitions are append-only too (see "status").

**Entry schema.**

Unlike local memory (§1), a global-memory entry is **flat** — every field is at
the top level; there is no `record` envelope (that nesting is local memory's, not
this one's).

```json
{
  "id":         "<stable id>",
  "timestamp_utc": "...",
  "author":     "<worker id | main_agent>",   // shared store ⇒ attributed
  "kind":       "counterexample",              // the strong category (§2.1)
  "claim":      "...",                          // what is asserted / explored
  "evidence":   "...",                          // verifiable: an explicit proof/construction; judgment: the reasoning behind it
  "verifiable": true,                           // ★ objectively checkable, or a judgment?
  "status":     "unverified",                   // lifecycle, §2.2
  "fact_id":    null,                            // back-link once promoted
  "links":      { "subgoal": "...", "predecessors": ["<id|fact_id>", "..."] },
  "glossary":   { }                              // symbol → definition introduced with this finding
  // …plus any kind-specific free-form fields (**extra) — e.g. a verification
  // entry's verdict/fact_id/write_error, or a master_guidance entry's
  // input_tokens/cost_usd — also flattened at the top level, NOT inside a record.
}
```

### 2.1 Kinds (categorization)

| kind | verifiable (default) | author | what goes in |
| --- | --- | --- | --- |
| `conclusion` | true | worker | a derived consequence of the statement (needs justification/proof as evidence) |
| `example` | true | worker | a (toy) example satisfying assumptions+conclusion; the construction is the evidence |
| `counterexample` | true | worker | a construction refuting a claim; the construction is the evidence |
| `proof_attempt` | true (when a sub-result is proved) | worker | an attempt on a subgoal; if a self-contained sub-result is proved, that is a verifiable claim |
| `plan` | false | worker | a subgoal decomposition / strategy (a judgment, not objectively checkable) |
| `dead_end` | usually false | worker | why a path failed; if killed by a counterexample it can be verifiable |
| `direction` | false | worker | "worth exploring X" — an unverifiable judgment |
| `obstacle` | false | worker | "X seems to block this route" — an unverifiable judgment |
| `master_guidance` | false | **main agent (via GPT-5.5-pro)** | the periodic high-intelligence strategic steer: critical decomposition, direction judgment, core thinking. Authoritative — workers heed it (but it is still not a correctness source). |
| `verification` | false | the worker's `fact_submit` (auto) | a trace of a verification outcome: the verdict, plus `fact_id` (on accept) or `repair_hints` (on reject). Logged automatically by `fact_submit` so the verifier's feedback is not lost — the verifier itself stays stateless. Siblings read these to learn from rejections. |
| `elaboration` | false | **main agent** | the periodic, high-signal-to-noise progress synthesis the main agent writes before consulting GPT-5.5-pro: mathematical verdict, closed/obsolete routes, interface contracts, dangerous heuristics, missing bridge lemmas (§2.4). It is the *input* prepared for the pro consult; `master_guidance` is pro's *reply*. Same cadence. |

Process-only categories (`branch_states`, `events`) stay in
**local memory**, not here — they are not findings. `verification_reports` is
not a kind: a verifier verdict attaches to an entry's `status` (§2.2).

**Scope rule that controls noise.** Every global-memory entry has a clear
scope: it is *a claim plus its evidence*. Objectively-checkable kinds
(`conclusion`/`example`/`counterexample`/`proof_attempt`) **must** carry an
explicit proof or construction as `evidence`. Unverifiable judgments
(`plan`/`direction`/`obstacle`/`master_guidance`) **must** set `verifiable:false`
so readers know they are opinions to test, not established results. This scoping
— not a politeness rule — is what keeps the shared store from becoming a dump.

**Writing guideline — unified definitions.** When you write a finding, **define
your symbols and reuse the project's terminology consistently** — check the
project glossary before naming something, and use the same symbol for the same
object as everyone else. A finding may carry an optional `glossary`
(symbol → definition). This is the same self-containment discipline the fact
graph enforces (§3); applying it early keeps global memory readable and lets a
verified finding carry cleanly into a fact without a terminology rewrite.

### 2.2 Status lifecycle

`status` is updated by appending a status event (append-only; current status =
the latest event for that `id`):

- verifiable entries: `unverified → verifying → verified (sets fact_id) | refuted`
- judgment entries: `open → supported | challenged`

A worker is **encouraged to keep pushing** `verifiable=true` entries through the
verifier: send to verify, on `wrong` revise the evidence, re-verify, until
correct — then it is promoted to a fact (§3, §4). The verify-and-repair loop
operates per-claim on the shared store.

### 2.3 master_guidance — the strategic channel

The main agent operates and schedules N parallel workers. On a fixed cadence
(e.g. hourly, or whenever all workers finish a round) it consults **GPT-5.5-pro**
for the most critical decomposition, direction judgment, and core thinking
(high intelligence, expensive ⇒ periodic, not per-round). It records the result
as a `master_guidance` entry. Workers read `master_guidance` and follow it as
authoritative steering. (Consequence for skills, decided later: this concentrates
the expensive intelligence at the strategic level, shrinking per-worker peer
consults.)

**Operations.** `append(kind, claim, evidence, verifiable, author, links, **extra) -> id`,
`set_status(id, status, fact_id=None)`, `read(kind)` (entries, status folded),
`search(query, kinds, limit)` (BM25).

### 2.4 elaboration — the synthesis channel (input to the pro consult)

On the same cadence as the strategic consult (§2.3), the main agent first writes
an **elaboration**: a single high-signal-to-noise synthesis of the project's
current state, read **only from the shared stores** — global memory (findings,
dead ends, recent verifications) and the fact graph (verified facts, the DAG,
proved vs. open) — **never** from a worker's private local memory (a layer
boundary). It follows a fixed template (mathematical verdict → closed/obsolete
routes → interface contracts → dangerous heuristics → missing bridge lemmas) and
a strict honesty discipline (goal stays fixed, cite `fact_id`s only, no numerical
distance estimates, no process telemetry). The *how* lives in the **`elaboration`
main-agent skill**, not in code.

The elaboration is recorded as an `elaboration` entry (`claim` = the one-line
verdict, `evidence` = the full templated body, `links` = cited `fact_id`s), then
handed to GPT-5.5-pro; pro's reply becomes the next `master_guidance` (§2.3).
Instead of peer workers reviewing each other, the main agent distills the shared
state and a single high-intelligence model reasons over it. Operationally it is
also what the main agent draws on to keep the human informed.

---

## 3. fact graph (project-shared, verified)

> **Terminology.** An **"ugly-proof"** — an "ugly-but-rigorous", self-contained,
> machine-checkable proof record — is exactly **a fact in this fact graph**, same
> thing. If the operator says "ugly-proof", they mean a fact node. ("Ugly" is the
> deliberate contrast with the *polished* arXiv paper, which a separate pipeline
> produces from the fact-graph DAG.)

**Purpose.** The single correctness source: a content-addressed DAG of
verifier-accepted facts that compose into a paper and support cascade revocation.
The essence is deliberately minimal — a readable node, a content-addressed id, a
predecessor DAG, cascade revoke — with no status, verifier_outcome, claim_summary,
see_also, or drafts/ on the node.

**Scope.** Project-shared, rooted at the project directory.

**Storage.** `<project_dir>/fact_graph/facts/<fact_id>.md` — one readable
markdown file per fact (file name = the bare-hex id) + `revocation_log.jsonl` +
`_revoked/<ts>/`. No `glossary.json`, no `drafts/` (rejected claims stay in
global memory as `refuted`).

**Fact node — 6 frontmatter fields + markdown body:**

```yaml
---
fact_id: 0056a49384644046          # content-addressed (bare hex)
problem_id: KMMP
author: KMMP_pro3                  # which worker produced it
predecessors: [7b6dd3df2e88fff5]   # bare-hex ids this depends on (the DAG)
glossary_introduces:               # symbols this fact defines (kept — see below)
  X: a complex manifold
  K_F: the canonical class of the foliation F
external_refs: [{"key": "HL26", "authors": ["Han", "Liu"], "title": "...", "arxiv": "2603.03817", "year": 2026, "cited_for": "Theorem 1.2"}]
---

## statement
<what was proved — self-contained: every symbol is defined here, in a cited
 predecessor's glossary, in the project glossary, or in the global glossary>

## proof
<the argument (markdown)>

## intuition          # optional
<one-liner>
```

- **`glossary_introduces` is KEPT (essential).** Without it the fact graph
  becomes unreadable — a fact could use a symbol nobody ever defined. Each fact
  records the symbols it introduces (symbol → definition); the project glossary
  `glossary.json` accumulates them. A **glossary-coverage check** (`fact submit`)
  flags any interesting symbol used in the body that is not defined anywhere
  **available**, where availability is the union of four layers (precedence
  low→high, a higher layer shadows a lower one): **global glossary** →
  **project glossary** → *cited predecessors'* `glossary_introduces` → *this
  fact's* `glossary_introduces`. The **global glossary**
  (`danus/core/glossary_global.json`, repo-wide, shared by **all** projects) holds
  universal notation — Z, Q, R, C, floor/ceil, gcd/lcm, intervals, the Greek
  parameter names, … — so a fact need not redefine `epsilon` or `Z+` every time;
  only project-specific symbols go in the lower layers. (Heuristic, advisory; the
  verifier is the backstop. The *other* proof-lint rules — handwave,
  chart-position refs — are **prose**, not code.)
- **`external_refs` is structured bibliography for cited external results** (a
  list of `{key, authors, title, arxiv, year, venue, doi, cited_for}` dicts;
  serialized as a one-line JSON flow-array; `[]` / absent for older facts). The
  worker fills it at `fact_submit` (grounded via `search_arxiv_theorems`); the
  paper pipeline's **reference auditor** corrects it post-hoc. It is **mutable
  metadata, NOT part of the `fact_id`** — hashing it would change the id (and break
  the DAG) on every audit, and would perturb every pre-existing fact's id. The
  cited keys themselves already live in `proof`, which *is* hashed. Read it via
  `external_refs(fact_id)`; rewrite it via `set_external_refs(fact_id, refs)`
  (touches only the metadata line, never the body or id).
- **`fact_id` is content-addressed:**
  `SHA256(json{problem_id, sorted(predecessors), sorted(glossary_introduces), normalized(statement), normalized(proof)})[:16]`.
  Same content ⇒ same id ⇒ natural dedup. Nodes are immutable
  (a changed statement/proof/glossary ⇒ a different id ⇒ a new file). `external_refs`
  is deliberately excluded (mutable metadata, above).
- **DAG:** `predecessors` are the bare-hex fact ids this fact depends on
  (its "depends-on"). References use bare hex everywhere — one convention.
- **Revocation:** revoking a fact moves it (and every descendant) to `_revoked/`,
  logs to `revocation_log.jsonl`; `add` refuses any predecessor already revoked.

**Deliberately not on the node (and where it lives instead):** `status` (a fact in
`facts/` is verified by definition) · `verifier_outcome` (redundant) ·
`claim_summary` (derive for an index when needed) · `see_also` · `drafts/`
(→ global memory `refuted`) · the text-hygiene lint rules — handwave,
chart-position refs, quantifier ranges (→ **prose** in the worker/verifier
prompts) · a persisted `verified_facts.jsonl` board (→ the **derived index** below: a
BM25 view computed on demand from `facts/`, never a stored second truth, so no
double-write drift). **Kept:** the glossary (data + the coverage check) — it is
what makes the graph readable.

**Derived fact index (`search`).** `search(query, limit)` rebuilds a BM25 view
over the fact bodies (statement + proof + glossary) **on demand** from `facts/*.md`
and returns the top `{fact_id, score, statement}`. It is the cross-worker recall
the LLM can't do by reading, serving **novelty** ("does a fact like this already
exist? — don't re-prove it") and **citation lookup** ("which verified facts bear
on my subgoal?"). Exposed as the `fact_search` MCP tool (worker + main). It is a
*read view*; the fact files stay the single source of truth.

**Operations (code = data-structure I/O only).** `compute_fact_id(...)`,
`add(problem_id, author, statement, proof, predecessors=[], intuition="",
external_refs=[]) -> fact_id`, `get_raw(fact_id)`, `list()`, `search(query, limit)`,
`predecessors(fact_id)`, `descendants(fact_id)`, `external_refs(fact_id)`,
`set_external_refs(fact_id, refs)`, `revoke(fact_id, reason)`.

---

## 4. Relationships & data flow (how they connect)

```
            ┌─────────────── per worker (private) ───────────────┐
 worker  →  │ local memory: notes / events  (rough recall log)    │
            └───────────────────────┬────────────────────────────┘
                    auto-publish a formed claim
            ┌───────────────────────▼──────────── project-shared ─┐
 all     →  │ global memory: <kind>.jsonl                         │
 workers    │   conclusion/example/counterexample/proof_attempt   │
 + main     │   plan/dead_end/direction/obstacle/master_guidance  │
 agent      │   each = claim + evidence + verifiable + status     │
            └───────────────────────┬────────────────────────────┘
                 verifiable=true → verify → repair → correct
            ┌───────────────────────▼──────────── project-shared ─┐
            │ fact graph: facts/<fact_id>.md (content-addressed)  │
            │   ★ the only thing a proof may build on (cite id)   │
            │   predecessors = DAG · cascade revoke               │
            └─────────────────────────────────────────────────────┘
```

**Invariants (load-bearing):**

1. **Correctness source = fact graph only.** Proofs cite `fact_id`. Global
   memory (even verifiable-but-unverified claims) is awareness, never a brick.
2. **Promotion is verifier-gated.** A claim enters the fact graph only by passing
   the verifier (§4 promotion).
3. **Append-only** everywhere (local + global + revocation log); status changes
   are appended events, not mutations. Fact files are immutable once written
   (a changed statement/proof ⇒ a different `fact_id`).
4. **Isolation of local memory.** Workers never read each other's local memory;
   the only cross-worker channels are global memory (awareness) and fact graph
   (truth).
5. **Content addressing.** `fact_id` is a pure function of content ⇒ dedup,
   stable references, cascade revocation.

**Promotion (a prose behavior, not a function).** When a `verifiable=true`
global-memory finding passes the verifier, the agent (per its prompt) writes the
fact with `FactGraph.add(statement=claim, proof=evidence,
predecessors=links.predecessors)` and back-links the finding with
`GlobalMemory.set_status(id, "verified", fact_id)`. There is deliberately **no
`promote()` function** — the decision to verify and the verify call are the
agent's; the library only offers the two data-structure writes.

### Code vs prose (the boundary)

| code (this library — touches the fixed JSONL / fact-graph files) | prose (prompts/skills — agent behavior) |
| --- | --- |
| local/global memory: append / read / search (BM25) | when to publish local→global; which `kind`/`verifiable` |
| fact node: serialize/parse, `compute_fact_id`, add/get/list, predecessors/descendants, cascade revoke | when to send to the verifier; the repair loop; when to promote |
| evidence-required-for-verifiable check; revoked-predecessor refusal | "global memory is awareness, never a brick — cite `fact_id`" |
| | "facts must be self-contained; no handwave / chart-position refs" |

Keep it that way: do not add orchestration code. If something is a *decision*, it
is prose.

---

## 5. Usage logic (typical round)

1. **Main agent**, periodically: consult GPT-5.5-pro → append a `master_guidance`
   entry to global memory.
2. **Worker**, each round:
   - read `master_guidance` + recent global memory (others' findings, dead ends)
     + relevant fact graph entries; recall own `local memory`.
   - reason; log raw thoughts/actions to `local memory`.
   - when a finding forms, auto-publish it to `global memory` with the right
     `kind` + `verifiable` + evidence.
   - push `verifiable=true` findings through the verifier; on accept, **promote**
     to the fact graph and build further work by citing the new `fact_id`.
   - record dead ends as `dead_end`/`obstacle` so siblings skip them.

This document is the contract those behaviors are written against. The Python
implementation lives next to it in `danus/core/` (`local_memory.py`,
`global_memory.py`, `factgraph.py`, `schema.py`, `bm25.py`); see `README.md` for
the API and usage instructions.
