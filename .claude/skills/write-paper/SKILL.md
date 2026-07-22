---
name: write-paper
description: Turn a project's verified fact graph into a publishable LaTeX paper in a configurable house style — a standalone amsart .tex with a real bibliography, compiled to PDF. Use when a project's target theorem is established and the operator wants the paper, or asks to write/revise/audit references for the paper for a project. NOT human-summary (a reader-facing progress report with no bibliography); this is the publication artifact, with verified citations, headed for arXiv / a LaTeX git repo.
---

# write-paper — fact graph → publishable paper

You are the main agent. This skill turns a project's **verified fact graph** into
a **publishable** LaTeX paper in a configurable house style: a standalone
`\documentclass{amsart}` `.tex` with a real manual bibliography, compiled to a
clean PDF, ready for arXiv / an Overleaf (or other) LaTeX git repo. It is the
publication sibling of `human-summary` (a reader-facing progress report with no
bibliography).

The heavy LaTeX work is delegated to a **local codex at extra-high (`xhigh`)
reasoning** — the same codex machinery the workers and the verify service already
use. The writer,
auditor, verifier, and reviser roles are wrapped behind the `write-paper` MCP
service (tools `paper_write` / `reference_audit` / `reference_verify` / `paper_revise`):
you call them with structured args, the tool assembles each role's prompt
internally (so the style guide and fact-graph bytes never enter your context) and
drives the codex with each role isolated by construction. The reference chain is
`auditor (offline, flags) → verifier (online, checks) → reviser (edits)`. You
orchestrate the stages, call these tools, gate on compilation, and surface the one
or two real decisions to the operator.

## When to use

- A project's target theorem is established in the fact graph and the operator
  wants the paper.
- The operator asks to **write**, **revise**, **audit references for**, or
  **push** the paper for a project.

Do not use it for the progress report (`human-summary`) or for the dense pro
consult input (`elaboration`).

## Source of content: the fact graph (never your memory)

Build the mathematics from the project's **verified facts**
(`<project>/fact_graph/facts/*.md`) and the verbatim goal in
`<project>/PROBLEM.md` — exactly as `human-summary` does, but for publication:

- Each fact's `## statement` is fully-quantified and self-contained → render into
  the paper's theorems/propositions (clean LaTeX, do not paraphrase loosely). Its
  `## proof` is the argument; `## intuition` feeds a proof sketch where useful.
- Load-bearing facts first: high dependency depth (headline results) and high
  in-degree (key lemmas). `predecessors` give you the internal `Theorem~\ref{}`
  cross-reference structure **with zero invention**.
- **Citations come structured, from the source.** Each fact's `external_refs`
  (key / authors / title / arxiv / year / cited_for) records the published
  results its proof cited. `driver/seed_ledger.py` aggregates them across the
  project into the starting `REFERENCE_LEDGER.md`. Do not re-mine citations from
  prose — that is the #1 failure mode (hallucinated references).
- **Preserve all mathematics. Invent nothing** — no assumptions, lemmas,
  citations, theorem labels, or definitions that are not in the fact graph. If a
  step is unclear, flag `[GAP: ...]`, do not smooth it over.

## Paper workspace: `<project>/paper/` (default) — and MULTIPLE papers per project

Per-project, alongside `fact_graph/` and `global_memory/`:

```
<project>/paper/                 # the DEFAULT paper (legacy paths — unchanged)
  PROJECT_BRIEF.md      # per-paper framing (interview the operator — see below)
  REFERENCE_LEDGER.md   # seeded from external_refs, verified by the auditor
  REVISION_LOG.md       # append-only round history
  main.tex / main.pdf   # the paper
<project>/TARGET.md              # the DEFAULT paper's finalized target (danus finalize)
```

Seed the workspace from `templates/` (copy `*.template` → the real names) if it
does not exist yet.

**One project can hold MULTIPLE papers** (e.g. a main theorem paper + a companion,
or several theorems each written up separately). Every `paper_*` tool and
`danus finalize` takes an optional **`paper_id`**:

- `paper_id` **omitted / `"main"`** → the **DEFAULT** paper on the **legacy** paths
  above (`<project>/paper/` + `<project>/TARGET.md`). Existing single-paper
  projects are byte-for-byte unchanged.
- any other `paper_id` (e.g. `thmB`) → an **isolated** workspace
  `<project>/papers/<paper_id>/` with its own `PROJECT_BRIEF.md` /
  `REFERENCE_LEDGER.md` / `REVISION_LOG.md` / `main.tex` / `TARGET.md`. So N papers
  never collide — each has its own files.

There is **one fact graph per project** (`<project>/fact_graph/`); papers never
fork or re-filter it. A paper's facts are simply the transitive-predecessor
**closure of its own headline set** — the SAME closure primitive the single-paper
pipeline already uses, merely rooted at that paper's recorded target. The three
shapes are one model — **a list of `{paper_id, headline_fact_ids}`**:

- **1 paper / 1 theorem** — the default: one entry, `paper_id="main"`.
- **N papers / 1 theorem each** — N entries, each a distinct `paper_id` and a
  single-fact headline; written in **separate workspaces** (no overwrite).
- **N papers / one multi-theorem paper** — an entry whose `headline_fact_ids` is a
  LIST of several targets; its fact set is the **union closure** of that list.

`paper_id` must be a single safe path segment (same validation as a project name);
it cannot escape the project dir.

## Style source

Two generic, self-contained layers under `style/`, neither naming an author or a
field:

- `style/STYLE_GUIDE.md` — the compact baseline house style (binding for *voice*:
  macros, theorem/proof shape, citations, cross-references, sentence-level rules).
- `style/PAPER_STRUCTURE.md` — the per-section content plan (binding for
  *structure*: what each part of the paper contains, by length tier — abstract,
  introduction, preliminaries, body, proofs, acknowledgements, bibliography).
  Field-neutral; uses placeholders, not any specific area's conventions.

Both are plain Markdown the operator may edit to encode their own preferences.

**Imitating your own past papers is strictly optional** — an add-on for authors
who already have published papers, not a dependency:

- `style/anchors/` — optional exemplar papers the operator drops in (one folder
  per paper, with its `.tex`) for the `STYLE_DISTILLER` to learn from (feeding the
  unified `STYLE_GUIDE.md`, which is the writer's single source of **voice**) and,
  optionally, for ONE of them — named deterministically by the brief's
  `structural_exemplar` field — to be imitated for **structure**. **Empty by
  default. The skill produces a complete, compilable paper from the two generic
  guides alone** — anchors only make the output sound more like the operator's own
  writing. The writer never "picks the closest" anchor: voice is the distilled
  guide (all anchors), structure is the single brief-named exemplar (or none).

The role prompts under `roles/` are generic and read directly; there is no
machine- or author-specific overlay.

## Per-call run logs (diagnostics)

Every `paper_*` tool returns a `log_path` and writes a full on-disk diagnostic
record there — the complete assembled prompt, codex's full stdout **and** full
stderr (not just the tail), the honest result, the tool's post-processing
decisions, and the returned envelope. On a non-`ok` or surprising result, **read
`log_path`** for the full assembled prompt + codex stdout/stderr + tool decisions
before retrying or reporting — it lets you localize the failure (prompt vs codex
vs tool logic) instead of retrying blind. The small envelope (status / returncode
/ `stderr_tail` / flags / paths) is unchanged; `log_path` is additive. Run logs
live under the paper's own `.runs/` (default `<project>/paper/.runs/`; a non-default
paper → `<project>/papers/<paper_id>/.runs/`), gitignored; set
`DANUS_WRITE_PAPER_RUN_LOG=0` to opt out (then `log_path` is `None`).

## Editorial quality bar — LENGTH IS A QUALITY CRITERION (your judgment, applied at every stage)

You are the paper's editor, and a good mathematics paper has a shape. Hold these
standards actively; they are as binding as correctness:

- **Length budget.** Two numbers, both binding: the **CURATION TARGET is ≤ 30
  pages** (~90K chars of LaTeX source) — size the support layer at stages 0/2 so
  the FIRST DRAFT lands at or under it, leaving headroom for verify-loop fills —
  and the **FINAL DELIVERABLE stays within 50 pages** (~150K chars). A few dozen
  pages is the practical limit of what humans read; past that the paper's flavor
  NECESSARILY degrades — referees stop reading, the narrative drowns, and results
  stop being findable. The ONLY exception: the operator EXPLICITLY commissions a
  detailed technical report (record that in the brief); absent that, a draft
  heading past ~150K chars means restructure or split (lever #4) — never keep
  inflating. Only epochal, Fermat-scale results justify hundreds of pages, and
  even those are published as a SERIES of papers, never one monolith.
- **Density signals.** Rough health checks: a strong paper carries ~10–30 labeled
  results; one theorem-sized idea per section; lemmas exist because the narrative
  needs them, not because the fact graph had them. Red flags that the shape has
  broken: 100+ labeled results in one document; helper-lemma sprawl around a
  single proof; repeated setup/notation blocks; proofs that read as computation
  logs (transcription instead of exposition).
- **The levers, in order — use these BEFORE accepting length.** (1) curate harder
  (present fewer results; the support-layer BINDING RULE); (2) cite, don't
  re-prove (standard machinery → precise citations); (3) render at expert
  compression (the synthesis doctrine in stage 5.5 — never one-lemma-per-fact);
  (4) **SPLIT into multiple papers** — the `paper_id` mechanism exists for exactly
  this: a deep technical development becomes its own companion paper ("Part II" /
  "technical companion"), and the main paper cites it the way it would cite any
  published work. The standard human practice for deep theorems is a short main
  paper + a full-details companion — NOT a 200-page monolith.
- **Where to apply it:** at stage 0, record a target length in the brief; at
  stage 2/2b, size the tree so the assembled paper fits the budget; during the
  verify→revise loop, WATCH the length — length pressure is a STRUCTURE
  signal, and the durable fix is UPSTREAM (write it right the first time: the
  proof-style spec, harder curation, cite-don't-re-prove), because post-hoc
  compression has almost no lever (next bullet); multi-paper restructuring is
  an operator-initiated fork, not your own exit; at deliver, a paper over
  budget is a quality defect to report, not to hide.
  **THE REVISER CANNOT COMPRESS — never order global compression.** Measured
  on a real paper: a dedicated compression-only round asked for −27K and
  delivered −0.5K; a retry with explicit per-section subtractive quotas
  delivered −3.8K; and every "pay by compressing while adding" round
  under-paid while the paper inflated ~5–14K/round. A patch-style reviser
  executes located edits; it cannot execute global restructuring. So NEVER
  issue "compress the paper (by N pages/chars)" — the ask silently
  under-delivers. What CAN work: YOU find the specific, mechanical
  redundancies yourself — a lemma proved twice, a definition declared twice,
  a duplicated setup block, two sections deriving the same identity — and
  order their removal as POINT EDITS ("delete the second proof under label Y;
  keep the first at Z; replace the body with \ref{Z}"). If a round or two of
  such located dedup does not recover the budget, STOP compressing — further
  rounds make the paper worse, not shorter. Report the overrun honestly as a
  delivery defect and put the structural fork (re-curate / split) to the
  operator.
  **THE CAP IS HARD — the freeze rule.** The moment the draft crosses the
  cap, ADDITIONS FREEZE — recovery is by the located dedup edits above,
  never by a global compress order; if they don't suffice, the freeze holds
  and you report. No goal — not even "make the verifier pass" — overrides
  the freeze: a verdict bought by inflation is a quality defect, not a
  success.

## The pipeline (you drive these stages in order)

### 0. PROJECT_BRIEF — interview the operator (do not invent)

If `<project>/paper/PROJECT_BRIEF.md` is absent, **conduct a short interactive
interview** with the operator to fill it: title, audience/venue, human authors
(and affiliations), which facts are the headline results, per-paper style
overrides, deadline. Write their answers into the brief. Never fabricate these —
they are the operator's call. (If the operator wants to skip and accept defaults,
record that; the writer then emits author placeholders.)

**Pre-fill `headline_fact_ids` from the finalized target.** When you seed the
brief, if the paper's `TARGET.md` exists (the default paper's `<project>/TARGET.md`,
or `<project>/papers/<paper_id>/TARGET.md` for a non-default paper — written by
`danus finalize [--paper <paper_id>]` when the operator approved the result as the
answer), copy its fact id(s) into the brief's `headline_fact_ids` field so the
finalized target is already the paper's headline. If `TARGET.md` is absent, leave
the field blank and **ask the operator** — and know that `paper_write` will
**refuse with `status="needs_target"`** until either the field is set or the
operator runs `danus finalize <project> [--paper <paper_id>] <fact_id>`. The skill
never guesses the target from the graph shape.

Two **structured fields** the brief carries (machine-read; keep the `field: value`
shape on its own line):

- **`headline_fact_ids`** — the fact ids that ARE this paper's target results
  (the theorems it foregrounds). This is the backbone of the default: the writer
  is given the transitive-predecessor **closure** of these targets — NOT every
  proven fact — and the reference ledger is seeded from the **same** closure, so
  the writer's facts and the bibliography agree and the auditor never sees phantom
  rows for side lemmas the paper never cites. Pre-fill it from `<project>/TARGET.md`
  if present, else ask the operator explicitly. If it is left blank AND no
  `TARGET.md` is recorded, the target is **UNSET** and `paper_write` refuses
  (`needs_target`) rather than guessing — run `danus finalize <project> <fact_id>`
  to record the target first.
- **`structural_exemplar`** — optional: the name of ONE folder under
  `style/anchors/` whose STRUCTURE this paper should imitate. Voice always comes
  from the unified `STYLE_GUIDE.md`; this names only the single structural
  exemplar. Blank = none. If the operator already has anchors, ask which (if any)
  to imitate structurally. **If `style/anchors/` is empty, still offer once** —
  "you can drop a few of your own papers into `style/anchors/` now to match your
  writing voice; want to? (a complete paper is produced either way)" — so the
  capability isn't hidden behind an empty folder. If they add some, run Stage 1a
  to distil them before writing.

### 1. Seed the reference ledger

```bash
python3 .../write-paper/driver/seed_ledger.py <project_dir> --headline <headline_fact_ids> --out <project>/paper/REFERENCE_LEDGER.md
# multiple papers: add --paper <paper_id> to scope the closure to that paper's
# recorded target and (with no --out) write the ledger into its own workspace:
python3 .../write-paper/driver/seed_ledger.py <project_dir> --paper <paper_id>
```

This aggregates the `external_refs` of the **target-closure facts** into
`unverified` rows. Pass the **same** `headline_fact_ids` you recorded in the brief
(stage 0) as `--headline` so the ledger's closure equals the writer's closure
(one closure, shared): the ledger then lists only references the paper's facts
actually cite — no phantom rows for proven-but-unused side lemmas. Omit
`--headline` to let the script resolve it identically (brief field → else the
finalized `<project>/TARGET.md`). If no target is recorded at all, the seed
**refuses** (matching the writer). (Verification is stage 4; `--all-facts`
restores the legacy all-facts seeding if ever needed.)

### 1a. Style preflight — distil the anchors if they changed (presence-triggered, once, operator-gated)

Before the writer stage, check whether the operator's own papers under
`style/anchors/` need to be distilled into the unified `STYLE_GUIDE.md`. This is
the only automatic trigger for the `STYLE_DISTILLER` — without it, papers an
operator drops into `anchors/` are silently ignored.

Trigger rule (all offline; the distiller only PROPOSES, never auto-applies):

- If `style/anchors/` is **empty** → skip (the two generic guides produce a
  complete paper; nothing to distil).
- If `anchors/` is **non-empty** AND **stale** — its newest content is newer than
  the `style/.distilled_at` marker, or the marker is absent — then run the
  `STYLE_DISTILLER` (`roles/STYLE_DISTILLER_PROMPT.md`) to **propose**
  `STYLE_GUIDE.md` updates. Present the proposals to the operator; on **accept**,
  apply the accepted edits to `STYLE_GUIDE.md` and **touch** `style/.distilled_at`
  (record the distill time). On reject, still touch `.distilled_at` only if the
  operator says the current guide stands (so a rejected-but-reviewed anchor set is
  not re-proposed every run) — otherwise leave the marker so it re-triggers.
- If `anchors/` is **unchanged** since the last distill (nothing newer than
  `.distilled_at`) → skip.

A tiny helper compares mtimes so the check stays clean:

```bash
bash .../write-paper/driver/anchors_stale.sh <skill_dir>   # rc 0 = stale (distil), rc 1 = fresh/empty (skip)
```

**Why operator-gated, never auto-applied:** the distiller edits the guide that
governs *every* future paper; a bad distill would silently corrupt them all. The
distiller proposes; the operator accepts; only then does `STYLE_GUIDE.md` change.
This step is still optional in spirit — with no anchors it is a no-op — but when
anchors exist and changed, it runs so they are not ignored.

### 2. Write (PAPER_WRITER) — produce `main.tex`

**Call the `paper_write` tool** (the `write-paper` MCP service). You do **not**
build the prompt by hand and you do **not** read the style guide, the structure
plan, or the fact graph into your own context — the tool assembles all of that
internally and drives the codex, so the large bytes never enter your window.

**First, curate — MANDATORY, and it is YOUR job, at EVERY level. `paper_subgraph`.**

> **BINDING RULE — never hand a writer the whole closure.** Every single `paper_write`
> call must be given a hand-picked **support layer** via `fact_ids`: the few key
> load-bearing results that call should PRESENT. It is **forbidden to pass the full
> closure** (or to omit `fact_ids` so the tool embeds it) **unless the closure is
> single-digit** (< 10 facts). Dumping all facts on one writer call is the root cause
> of overflow, the chunked fallback, and flat/bloated output — do not do it. If you
> think "this piece is small enough to just send its facts," check the count first;
> if it is ≥ 10, curate.
>
> **This applies RECURSIVELY / fractally.** A hard sub-result written as its own
> lemma-chapter is STILL a `paper_write` call, so it ALSO gets a curated support layer
> — not that sub-result's whole closure. If that chapter's support layer leans on a
> deeper load-bearing result, that deeper result becomes its OWN curated `paper_write`
> call (its own chapter/sub-paper), which YOU then compose in (a written body slotted
> as a section — you do the stitching; see below). The paper is a TREE of curated
> single-pass writes you design and assemble, never one writer call swallowing a big
> fact set. "Pick the support layer" is the intelligence that stays with you at every
> node of that tree; the writer only renders what you hand it.

The target's full transitive closure can be hundreds of facts; embedding every
proof would overflow a single writer pass. So do what a human author does: read a
**compact skeleton** and SELECT the load-bearing subset to write up. Call

```
paper_subgraph(project=<project>, headline=[<target fact ids>|omit], paper_id=<paper_id|omit>)
```

It returns, deterministically (no codex, no writes), `{status, headline,
headline_source, count, facts}` where each `facts[i]` is `{id, statement (one-line),
predecessors, dependents (in-closure in-degree — higher = more load-bearing),
glossary_introduces}` in topological order. Read it, pick the results the paper
should PRESENT (the headline theorems + the lemmas their proofs actually turn on —
NOT every granular intermediate step; those get cited), and write short editorial
`instructions` (how to section, what to foreground). An unset target → the same
`needs_target` refusal as `paper_write` (run `danus finalize` first).

**Then write** — pass your selection + direction to `paper_write`:

```
paper_write(project=<project>, headline=[<target fact ids>], paper_id=<paper_id|omit for default>,
            fact_ids=[<the load-bearing subset you selected>], instructions="<sectioning / emphasis>")
```

- `fact_ids` — the subset from `paper_subgraph` to PRESENT in full. The tool embeds
  only these (statement + proof) plus their **direct-predecessor statements** as
  `\ref`/`\cite` context (the granular lemmas are cited, not reproduced) — so a
  curated paper fits ONE pass. **Omit `fact_ids` ONLY when the closure is
  single-digit** (< 10 facts); on any larger closure omitting it (⇒ whole-closure
  embedding ⇒ chunked fallback ⇒ bloat) is the mistake the BINDING RULE above forbids.
  Unknown ids → `status="bad_fact_ids"` (no paper); ids outside the closure are kept
  with a `fact_id_warnings` note.
- `instructions` — your editorial direction, embedded verbatim as an authoritative
  `MAIN_AGENT_INSTRUCTIONS` block (wins over the writer's default structure, never
  over the PRIME DIRECTIVE / style voice / the mathematics).

- `project` — the project name (resolved under `DANUS_AGENTS_ROOT`).
- `paper_id` — WHICH paper in the project (multiple papers per project; one fact
  graph). Omit / `"main"` → the default paper on the legacy `<project>/paper/`
  paths; any other id → the isolated `<project>/papers/<paper_id>/` workspace. The
  brief / ledger / TARGET.md the tool reads are rooted at that paper's workspace.
- `headline` — the paper's **target** fact ids (the headline results). This is
  the DEFAULT scoping: the tool embeds only the target's transitive-predecessor
  **closure**, in topological order, with **zero invention** — NOT every proven
  fact. Omit `headline` to let the tool resolve it the same way the ledger did:
  the brief's `headline_fact_ids` field, else the finalized `<project>/TARGET.md`.
  The tool returns `headline` (the resolved target ids used) and `headline_source`
  (`arg` / `brief` / `target`). If the target is **UNSET** (no arg, no brief field,
  no `TARGET.md`) the tool returns `status="needs_target"` with a `candidates` list
  (the terminal facts) and writes **no** `main.tex` — **run `danus finalize
  <project> <fact_id>`** (or fill the brief) and call it again. It never guesses.
- The **structural exemplar** is read from the brief's `structural_exemplar`
  field (one anchor to imitate for STRUCTURE); there is no per-call anchor arg.
  Voice always comes from the unified `STYLE_GUIDE.md`.
- **`paper_write` does NOT stop the worker swarm by default** — entering
  write-paper does not always mean the whole problem is proven; a *partial* result
  can be written up while the swarm keeps exploring the rest. **If you already
  stopped the swarm because the whole problem is proved** (the completion rule in
  `CLAUDE.md` / the main-agent contract), this fork is moot — the swarm is already
  down; just write the paper. **Otherwise (a partial result, exploration ongoing),
  you decide:** at the start of write-paper (Stage 0) surface the fork to the operator
  — *"Start the paper — stop the swarm's exploration, or keep it running? (A partial
  result can be written up while the swarm keeps proving the rest.)"* On **stop** →
  call `paper_write(stop_workers=True)` (or `danus stop <project>`); on **keep** →
  the default (no stop). When you do request a stop it is graceful (never drops an
  in-flight verified round), idempotent, and failure-isolated; the tool reports it
  in a `swarm_stop` field (`result` / `noop` / `error` / `skipped`).

Internally the tool embeds, in full: the role contract (`roles/AGENTS.md` — the
PRIME DIRECTIVE) and `roles/PAPER_WRITER_PROMPT.md`; the **unified**
`style/STYLE_GUIDE.md` (voice, distilled across all anchors) and
`style/PAPER_STRUCTURE.md`; `boilerplate/acknowledgement.md`; `PROJECT_BRIEF.md`
and the seeded `REFERENCE_LEDGER.md`; the fact-graph math of the **target
closure** (each fact's `## statement` / `## proof` / `## intuition` + the
predecessor DAG, verbatim); and, iff the brief's `structural_exemplar` names an
existing anchor, that ONE anchor as a structural exemplar. Those codex-facing
fixed files (`roles/`, `style/`, `boilerplate/`) live under
`agents/skills/write-paper/`, **not here** — the MCP reads and embeds them; you never do. It
writes codex's stdout to `<project>/paper/main.tex` (a full `\documentclass{amsart}`
… `\end{document}`, real `\ref`/`\cite`, manual `\begin{thebibliography}{99}`).

The tool returns a small dict — `{tex_path, status, returncode, headline,
headline_source, selected_facts, fact_id_warnings, gaps, stderr_tail, log_path}` (or
`{status:"needs_target", message, candidates, log_path}` when the target is unset,
or `{status:"bad_fact_ids", unknown_fact_ids}` when a selected id is not in the
graph). **Honesty:** it reports `status="ok"` only
on a zero exit with non-empty output; a nonzero codex exit, an empty artifact, or
a timeout is `status != "ok"` and **nothing is written** — do not treat a non-`ok`
result as a produced paper, and a `needs_target` result means you must record the
target first (`danus finalize`). `headline`/`headline_source` report which target
ids were used and where they came from. The `gaps` list is the `[GAP: ...]`
markers the writer left; act on them. The tool does **not** compile — the compile
gate is stage 3.

**Auto-chunking — the extreme fallback.** Curation (`fact_ids`) is the primary
answer to a large closure: a well-chosen subset writes in one pass. But if even the
prompt you assembled is still over budget (`DANUS_PAPER_WRITE_CHUNK_CHARS`, default
~800000 chars ≈ ~200K tokens) — a huge selection, or `fact_ids` omitted on a giant
closure — `paper_write` falls back automatically to **chunked** generation: a
**planning pass** (one codex call on the STATEMENTS ONLY of the set being written →
the fixed preamble + front matter + a section plan assigning every fact + the
bibliography), then **per-section fill** (one codex call per section, each given THIS
section's full proofs + the fixed preamble/labels + every other result's statement
for `\ref`), then a deterministic **stitch** into one `main.tex`. When you passed
`fact_ids`/`instructions`, the fallback chunks exactly that curated set and the
planner honors your instructions. Each call is still a NON-AGENTIC isolated codex
(empty cwd, everything embedded, no tool calls) — chunking is decided in Python and
sliced by section, not an agentic retrieval writer. The result carries `chunked:
true` and `sections: <n>`. Under budget → the single-pass path runs unchanged.
**Honesty is preserved:** if the planner or any section writer returns non-ok, or a
deterministic coverage check finds an assigned fact unassigned/duplicated,
generation fails honestly (`status="chunk_failed"`, `failed_phase`) and **no
`main.tex` is written** — a partial paper is never emitted. Cross-section coherence
(a `\ref` that does not resolve, a seam claim) is caught downstream by the compile
gate (stage 3) and `paper_verify_math`. If chunking keeps failing, prefer selecting
a smaller `fact_ids` subset, or split the work into multiple papers via `paper_id`.

**Manual fallback — you assemble and drive codex yourself (last resort).** If
`paper_write` returns `status="chunk_failed"` (or any non-`ok` you cannot resolve by
curating a smaller `fact_ids` subset or splitting into multiple papers), fall back to
the flexible manual path: **you** write the paper by driving codex directly. This is
the one place you assemble the codex prompt by hand — use your judgment (curate the
facts, restructure the sections, adjust emphasis) to get past whatever the
deterministic path choked on.

1. **Get the material.** Read the failed run's **`log_path`** — it holds the full
   assembled prompt (role contract + style guide + structure + brief + ledger + the
   fact bodies). Reuse it as-is, or re-assemble your own from the pieces you control:
   your curated `fact_ids` (each fact's `## statement`/`## proof` from
   `<project>/fact_graph/facts/*.md`, or via `paper_subgraph`), `style/STYLE_GUIDE.md`
   + `style/PAPER_STRUCTURE.md`, the brief, and the seeded `REFERENCE_LEDGER.md`.
2. **Drive codex yourself.** The prompt is large — write it to a temp file and put it
   on **stdin** (never argv), and run the repo's codex wrapper at `xhigh`, read-only
   (the same flags the tool uses — see `danus.authoring.driver`):
   ```bash
   bin/codex exec --model "$DANUS_CODEX_MODEL" --config model_reasoning_effort=xhigh \
     --sandbox read-only --skip-git-repo-check - < /tmp/writer_prompt.md \
     > <project>/paper/main.tex          # or <project>/papers/<paper_id>/main.tex
   ```
   In this fallback the bytes DO enter your context (you read/assemble the prompt) —
   that is the trade for flexibility, and it is acceptable because it is the rare last
   resort, not the hot path.
3. **Then re-enter the gates — verification is NOT bypassed.** Your hand-written
   `main.tex` goes through the SAME safety net as any tool-written one: the compile
   gate (stage 3), the reference audit/verify (stages 4/4.5), and **`paper_verify_math`**
   (stage 5.5). The manual fallback loosens only *how the paper is written*, never
   *how it is verified* — a hand-written paper with a broken proof is still caught and
   still blocks deliver.

**Honesty:** exactly as on the tool path, a paper is "produced" only after it
compiles AND passes `paper_verify_math`. Never present a hand-written `main.tex` as
done before the gates pass.

### 2b. DEEP theorems — the CHAPTER TREE (write chapters with the writer; never dump facts on the reviser)

When the target's load-bearing content is too deep for one curated single-pass write
(hundreds of novel facts — e.g. a paper whose verifier gaps keep exposing deeper
sub-lemmas), do NOT try to close it by feeding fact piles to `paper_revise` — an
accretion of 100+ reviser-inserted lemmas produces a flat, disorganized blob and
converges terribly (measured). And do NOT fall back to the auto-chunker to "handle"
it. Instead, YOU author the paper as a **tree of curated single-pass writes**:

1. **Design the tree** (you, from the `paper_subgraph` skeleton): a HOST frame +
   one chapter per deep development. The HOST's support layer is the main theorem,
   its direct combination inputs, and the chapter-level results — its instructions
   say: STATE each chapter-level result fully, with the one-sentence proof "The
   complete development is given in the dedicated technical section inserted
   below." (never a fabricated `\ref`), and prove ONLY the top-level assembly.
   Each CHAPTER is its own `paper_write` call with its own workspace
   (`paper_id=ch_*`), its own brief/ledger (`seed_ledger.py --paper`), and a
   **curated support layer (≤ ~10 facts — the BINDING RULE applies at every
   node)**; its instructions say: ONE short intro paragraph, a setup section, the
   lemmas in logical order, complete proofs; any prerequisite that is a result of
   the larger paper is declared explicitly in the setup ("we assume, established
   earlier in this paper: ...") — never re-proved, never hand-waved.
2. **Write the nodes** — independent `paper_write` calls (parallelize freely); a
   chapter that overflows the writer's single-response limit is a sign to SPLIT it
   into sub-chapters (deeper tree), not to chunk. Compile each node; run
   `paper_verify_math(paper_id=ch_*)` per chapter — its per-chapter verdict flags
   chapter-INTERNAL defects to fix now (a mangled induction, a dropped hypothesis)
   vs setup-imports (discharged at assembly, expected).
3. **Stitch (YOU are the editor — mechanical transforms only):** extract each
   chapter's body (drop title/abstract/acks/bib), demote sectioning one level,
   prefix every `\label`/`\ref` with `chX:`, wrap as
   `\section{<title>}\label{sec:tech-chX}`, insert the chapters **in topological
   order** before the host's assembly section, merge missing `\usepackage`s /
   `\newtheorem`s / macros / `\bibitem`s into the host (dedupe by name/key), and
   replace each host pointer-proof sentence with `Section~\ref{sec:tech-chX}`.
   Keep the stitch as a rerunnable script; **but every post-stitch edit lives on
   the merged file — re-stitching discards it**, so freeze the tree first, stitch
   once, then edit.

   **Stitch pitfalls (measured in a cold-start test — read before stitching):**
   - **Record a manifest at design time.** The pointer-proof sentences are
     byte-identical and carry no chapter hint; some chapters are pure support (no
     pointer at all). When you design the tree, record `{host theorem label →
     chapter paper_id}` and the intended insertion order in the tree-design file —
     don't force the assembler to re-derive it by reading statements.
   - **Ordering with delivered cycles.** Chapters written independently may have
     GENUINELY cyclic setup-imports (A assumes B's result, B assumes A's). No
     insertion order fixes that at stitch time — pick the order that points the
     most load-bearing arrows backward, and leave the residual forward edges to
     the seam-discharge stage (conditional restatement + later discharge).
   - **"Assembly section" means the main-theorem proof section.** If the host has
     OTHER full-proof sections that consume chapter results, they must ALSO end up
     AFTER the technical sections (relocate them), or the sequential verifier will
     reject the forward dependence.
   - **Macros: dedupe by name is unsafe on semantic conflicts.** Same-name macros
     with different bodies (e.g. `\join` as `\operatorname{join}` vs `\vee`)
     silently change a chapter's math if first-wins. Diff the bodies; on a
     semantic mismatch, rename in the chapter body. Preserve `\renewcommand` lines
     as-is (a chapter may legitimately renew a kernel command like `\H`); never
     downgrade them to `\newcommand`.
   - **Packages must merge BEFORE `hyperref`** (load-order trap); `\newtheorem`
     display-name variants for the same env — pick one.
   - **Bibliography:** import only `\bibitem`s whose keys are actually `\cite`d;
     first-wins on duplicate keys; DROP/replace keys the verified ledger marks
     rejected/unverified (a mechanical stitch happily keeps bad keys — check the
     ledger).
   - **The compile gate does NOT catch multiply-defined labels** — after
     namespacing, grep for duplicate `\label{...}` yourself.
   - **Chapter residue:** each chapter body still carries its own disclosure
     remark / `\note` annotations; the merged paper has N copies. Strip the
     duplicates at stitch time or queue them for the reviser — decide, don't
     ignore.
4. **Discharge the seams (reviser rounds on the merged paper, `notes=` trigger):**
   rewrite every chapter setup item "established earlier in the larger paper" to a
   precise `Theorem~\ref{...}` of THIS document; replace stale `[cite/blocker]`
   notes with precise `\cite` of ledger-verified keys; point the host assembly's
   invocations at the chapter theorems. **SEAM ACYCLICITY (load-bearing):** the
   whole-paper verifier reads SEQUENTIALLY — a proof may rely only on EARLIER
   results. Insert chapters in dependency order, and a setup item must point
   BACKWARD; if a chapter genuinely needs a LATER result, restate the affected
   theorem as explicitly conditional ("Assume (H). Then ...") and add, at the later
   point where (H) is proved, the one-sentence unconditional combination. Better:
   prevent it upstream — write chapter briefs so each chapter assumes only EARLIER
   chapters' outputs.
5. **Gates as usual on the merged paper:** compile + reference chain (reuse the
   project's VERIFIED ledger for the merged workspace) + `paper_verify_math` →
   iterate the discharge (and, for a genuinely missing development, grow the tree:
   one more small curated chapter, stitched in — never a fact pile to the reviser).

### 3. Compile-verify (hard gate)

```bash
bash .../write-paper/driver/compile_verify.sh <project>/paper/main.tex
```

Runs the LaTeX engine (default `pdflatex`; `xelatex`/`lualatex`/`tectonic` via
`TEX_ENGINE`); fails on any LaTeX error or any undefined citation/reference. With
no TeX Live installed, `TEX_ENGINE=tectonic` (after `bash scripts/install-tex.sh`)
is the zero-dependency engine.
**Do not proceed past a failed compile** — feed the offending log lines back to a
codex revise round (stage 5) and recompile. The compile is the **tool's /
orchestrator's** gate, never the reviser's own self-check (the reviser runs in an
empty cwd and cannot compile). **Authority boundary:** `paper_write` does NOT
compile — run this gate once on the writer's first `main.tex`. `paper_revise`
**retries the compile internally** (re-drives the reviser with the failing log
until the .tex compiles, or fails honestly), so a `paper_revise` returning
`compile="ok"` has ALREADY compiled — do **not** redundantly re-run this gate after
it; only run it after `paper_write` or a hand edit. A broken `.tex` must never be
delivered or pushed.

### 4. Reference audit (REFERENCE_AUDITOR) — FLAG, never fabricate

**Call the `reference_audit` tool.**

```
reference_audit(project=<project>, paper_id=<paper_id|omit for default>)
```

The tool assembles the auditor prompt (`roles/AGENTS.md` +
`roles/REFERENCE_AUDITOR_PROMPT.md` + `main.tex` + `REFERENCE_LEDGER.md` — and
**nothing else**: the auditor never sees the fact graph, the style guide, or the
structure plan) and drives a codex that has **no tools and no network**. The
auditor **only flags** entries it cannot vouch for; **verification is
`reference_verify`'s job** (Stage 4.5), not the auditor's. It returns
`{findings, ledger_path, status, returncode, log_path}`
and
writes **no** `main.tex`.

Take the auditor's `findings` and hand them straight to `reference_verify` (Stage
4.5) — that is where the flagged entries get checked online. As with
`paper_write`, a non-`ok` status means the audit run failed — do not treat empty
findings as a clean bibliography.

### 4.5 Reference verify (REFERENCE_VERIFIER) — online per-entry verification

**Call the `reference_verify` tool** with the auditor's findings.

```
reference_verify(project=<project>, findings=<the auditor's findings text>, paper_id=<paper_id|omit for default>)
```

This is the **online** half of the reference chain — `auditor (offline, flags) →
verifier (online, checks) → reviser (edits)`, symmetric to the proving chain
`worker → verifier → fact_graph`. The tool assembles the verifier prompt
(`roles/AGENTS.md` + `roles/REFERENCE_VERIFIER_PROMPT.md` + `main.tex` +
`REFERENCE_LEDGER.md` + the auditor's `findings` — and **no fact graph, style, or
structure**) and drives a codex over the **networked** path:
`--dangerously-bypass-approvals-and-sandbox` + the danus gateway at
`DANUS_ROLE=verifier` (exposing only `search_arxiv_theorems`, minimum privilege) +
codex's built-in `web_search`. The codex still runs in an empty cwd, so it cannot
touch the project tree; its only outward reach is the gateway's read-only tool +
web.

Per flagged entry it does: `search_arxiv_theorems(statement/title)` → best
`arxiv_id` → open `https://arxiv.org/abs/<id>` for the authoritative
authors/title/year + journal-ref, confirming it is the **same** paper (not merely
"a similar theorem exists"); non-arXiv references (textbooks / old journals) →
targeted web search at an authoritative source (publisher / DOI / zbMATH / DBLP).
It emits one verdict object per entry (`verified` / `corrected` / `rejected` /
`unverifiable` / `retarget-internal`) plus a one-line replacement suggestion for
the reviser, **writes the confirmed metadata back into `REFERENCE_LEDGER.md`**
(each promoted row marked `verified-by: verifier` + `source_url`), and returns
`{verdicts, ledger_path, status, returncode, stderr_tail, log_path}`. It **never** touches
`main.tex` — applying the replacements is the reviser's job (Stage 5).
`unverifiable` entries keep their `[cite/blocker]` flag.

**Honesty:** the ledger is updated ONLY on an honest `ok` run (zero exit, non-empty
output). A nonzero exit / empty output / timeout → `status != "ok"` and the ledger
is **not** touched — no false promotion. A degraded/offline run whose verdicts are
all `unverifiable` promotes nothing.

**Handoff to Stage 5.** Collect each verdict's one-line `replacement_suggestion`
and pass them to `paper_revise` as its `citation_fixes` argument — that is the
verify→revise seam. The reviser applies those fixes against the `\bibitem`/ledger
keys already present (never invents metadata); any `[cite/...]` still needing an
external source and not covered by the fixes stays a `[cite/blocker]` marked
`\note{[deferred: to reference_verify]}`. The three-stage chain is: **auditor flags
offline → verifier verifies online + writes the ledger → reviser applies the fixes
into `main.tex`.**

### 5. Revise (PAPER_REVISER) — on compile failures, verifier fixes, operator annotations, or a math `wrong`

**Call the `paper_revise` tool** when: a compile failed; the verifier returned
citation fixes to apply; the operator added `\edit{...}` / `\note{...}` editorial
annotations; or `paper_verify_math` returned `wrong` (pass its located findings —
and, for any re-rendered fact, the fact's verified proof — via `notes`; Stage 5.5
says how).

```
paper_revise(project=<project>, compile_log=<failing pdflatex lines>, notes=<operator direction / math findings + verified proofs>, citation_fixes=<verifier replacement suggestions>, paper_id=<paper_id|omit for default>)
```

The tool assembles the reviser prompt (`roles/AGENTS.md` +
`roles/PAPER_REVISER_PROMPT.md` + `style/STYLE_GUIDE.md` + `main.tex` + the
`REVISION_LOG.md` tail + the trigger you passed as `compile_log` / `citation_fixes`
/ `notes` — and **no fact graph**), drives a codex, and — on a clean
gate — overwrites `<project>/paper/main.tex`. Pass the offending log lines from a
failed compile as `compile_log`, the verifier's per-entry replacement suggestions as
`citation_fixes` (Stage 4.5's seam), and any operator editorial direction or math
findings as `notes`.

- **Change scope is governed by the trigger type.** A `compile_log` → the reviser
  fixes only the compile errors; `notes`/`citation_fixes` → it acts only on those
  items; `gap_fill` (verifier feedback + facts to add) → it proves the supplied
  facts into the paper (the one trigger allowed to change formal content); no
  trigger → the global style-audit rewrite. (The tool prepends a `MODE:` line the
  reviser branches on.)
- **The compile is the tool's gate now, not the reviser's self-check, and
  `paper_revise` retries it internally.** After the leak gate the tool compiles the
  revised .tex outside the reviser; if it fails, it re-drives the reviser with the
  failing log (carrying the same `notes`/`citation_fixes`) up to
  `DANUS_WRITE_PAPER_COMPILE_ATTEMPTS` (default 3). On success it writes `main.tex`
  and returns `compile="ok"` + `compile_attempts`. If the LaTeX engine is missing it
  cannot gate what it cannot run: it writes once, returns `compile="skipped: no
  engine"`, and you should run the standalone `compile_verify.sh` when a toolchain
  is available. If attempts are exhausted it does **not** overwrite `main.tex`,
  quarantines the last attempt to `main.uncompiled.tex`, and returns
  `status="compile_failed"` with a log tail.
- **The revise output passes the same leak gate as `paper_write`.** A `fact_id` /
  machinery token in the revised .tex → quarantined to `main.leaky.tex`, `main.tex`
  not overwritten, `status="leak"`.
- **`REVISION_LOG.md` now carries the reviser's real round summary** (the
  `%%%REVISION_SUMMARY%%%` section of its output), not a boilerplate stub — the tool
  splits the output and writes the actual summary as the log entry body (or a
  `[degraded: ...]` note if the reviser emitted no summary section).

It returns `{tex_path, status, returncode, revision_log_path, leak_findings,
compile, compile_attempts, stderr_tail, log_path}`; on a non-`ok` codex status nothing is
overwritten. Recompiling standalone (stage 3) after a revise round is your
independent confirmation, but the tool has already gated the compile internally.

### 5.5 Math-verify (WHOLE-PAPER) — re-verify the paper AS WRITTEN (HARD GATE)

**Call the `paper_verify_math` tool.** This is the gate that makes the paper — not
just its facts — correct.

```
paper_verify_math(project=<project>, paper_id=<paper_id|omit for default>)
```

**Why this stage exists.** Each fact was verified individually before it was ever
written. But the paper is a **different artifact**: the writer re-renders and
re-stitches those facts for publication — concising, dropping "obvious" steps,
adding *"it suffices to…"*, *"WLOG…"*, and inline reductions that were never
themselves a fact. Those seams are exactly where a correct set of facts becomes an
incorrect paper. A fact's earlier `correct` verdict does not transfer to its
re-stitched paper rendering.

**What the tool does.** One fresh **paper-math verifier** codex (a dedicated role —
separate from the fact-submission verifier and the reference verifier; a one-shot
run, no resident service) reads the **whole** `main.tex` development in reading
order plus the confirmed `REFERENCE_LEDGER.md`. It **trusts the confirmed precise
citations** and scrutinizes the paper's **own reasoning and self-containedness** —
no fact graph, no slicing. A paper that leans on a lemma it never proves or
notation it never defines is judged `wrong`, correctly: the paper, not the
verifier, has to be complete. The tool writes ONE `whole-paper` row to
`<paper>/VERIFY_LEDGER.md` (**only the tool writes verdict rows**) and returns
`{status, verdict, repair_hints, body_chars, ledger_path, log_path, deliver_ok,
blockers}`.

**Honesty:** a failed verify **RUN** (codex error, unparseable verdict) is
`status="verify_error"` — **NOT** a paper that passed; `status="passed"` requires
an actual `correct` verdict. Do not treat a `verify_error` as a clean paper.

**On `wrong` — the verify → revise loop (you drive it, reading the ledger, not
your memory).** `repair_hints` carries the verifier's located findings (which
theorem/paragraph, what is broken). For each finding:

−1. **TRIAGE FIRST — the verifier's verdict is a signal, not an order.** Before
   fixing anything, classify each finding with YOUR OWN mathematical judgment:
   - **A real gap** — the paper's own NOVEL load-bearing content is missing,
     circular, or wrongly argued (a new induction, a new positivity /
     no-cancellation argument, a new comparison theorem, a genuinely flawed
     deduction). ONLY these get the fact-curation + revise treatment below.
   - **A standard-type computation flagged for being summarized** — the step's
     TYPE is textbook technique an expert reproduces mechanically (a finite
     explicit low-degree expansion, a standard blowup/projective-bundle
     pushforward, a routine circuit/rank argument, a Kunneth/direct-sum
     factorization) and the paper states what is computed and the outcome. Do
     **NOT** auto-fill these: stuffing every standard computation into the paper
     is how the editorial length budget dies and the paper's flavor with it.
     Leave the text as written, RECORD the finding honestly (ledger + your
     deliver report, verbatim), and hand the fill-or-not decision to the
     OPERATOR — whether a standard-computation gap is worth pages is a human
     call, not yours and not the verifier's.
   - **A real gap that needs MANY facts — KEEP CURATING, KEEP WRITING.** If
     filling a gap would take dozens or hundreds of facts, that is NOT a
     reason to stop or defer. It means the gap is itself a development that
     gets the SAME treatment as the paper: **extract its support layer and
     keep writing** — and recurse again if a sub-gap is deep in turn. The
     development's full-closure size is NOT the decision metric — measuring
     the transitive closure and giving up is the original overflow fallacy in
     new clothes. Concretely, recurse the curation principle onto the
     development itself: select ITS OWN support layer (the ~10–20 facts that
     carry the argument — the base cases, the induction mechanism, the
     endpoint), and write it as a dedicated section at expert compression (the
     synthesis doctrine), triaging its sub-steps like any other content
     (standard-type sub-computations summarized, per the active criteria).
     **THE TOOL FOR A DEEP GAP IS THE WRITER, NOT THE REVISER.** The
     dedicated section is a NEW `paper_write` call (its own curated support
     layer and brief, stitched in per stage 2b — same seam rules), after
     which the reviser only wires the seams (`\ref`s, setup pointers).
     `paper_revise(add_facts=…)` is reserved for LOCATED point repairs — 
     re-rendering a mangled proof, adding the one missing step, a handful of
     facts (~≤10) — never for a development: a fact pile fed to the reviser
     accretes a flat lemma blob and inflates the paper ~5–14K/round
     (measured), which is exactly the failure stage 2b exists to prevent.
     **THE GAP-FILL BRIEF CONTROLS THE LENGTH — the writer has no idea of
     your budget.** A writer call knows only what you hand it; its default
     register is "standalone paper" (title, intro, notation section), and
     nothing in its role prompt sees the host paper. So every gap-fill
     `paper_write` brief states: (a) REGISTER — "one SECTION of an existing
     paper, NOT a standalone paper: no title/abstract/intro/notation
     section; open inside the host's standing conventions" (attach the
     host's setup and the labels it may `\ref`); (b) INTERFACE — exactly the
     statement(s) it must deliver, what it may assume from earlier sections,
     and WHICH steps are the section's pivots (name them — those get derived;
     every unnamed step stays at mechanism+outcome); (c) a NUMERIC target from the expert-compression calibration
     (a deep-gap section: 2–3 pages / 6–10K — a 2–4K frame plus ~2–4K of
     derivation per novel pivot; see THE PIVOT IS NOT COMPRESSIBLE); (d) the
     proof-style spec, verbatim. Input curation is the other half of the
     lever: a ~10–20-fact support layer physically cannot balloon into 30
     pages — hand it a closure instead and no brief will save you.
     **Calibrate the cost at EXPERT COMPRESSION, not transcription:** a human
     expert rendered a comparably deep flagged step in **under 2K chars**; a
     gap fill should typically land at 1–5K. If your estimate says +30K, you
     are estimating transcription — fix the instruction, not the budget.
     **If the budget is genuinely tight, the cause is almost always UPSTREAM
     STRUCTURE, not the new content:** earlier sections are wasting space
     (verbose renders, redundant setup/notation blocks, lemma sprawl,
     duplicated disclosures). Recover the space by LOCATED dedup edits you
     identify yourself (never a global compress order — the reviser cannot
     execute one; see the editorial bar), then write the gap. You do NOT
     defer a gap on your own authority: the companion-paper /
     conditional-statement / override forks exist, but they are decisions
     only the OPERATOR can initiate; your default is always: as long as a
     gap stands, you write.
     **THE SPIN-OFF FORK — raise it, don't decide it.** If the paper you have
     is otherwise a sound, well-structured ~30-page article, but your honest
     estimate says this ONE detail cannot be filled within a few pages even
     at expert compression, do not silently grind it in and do not silently
     drop it: REPORT the state and ASK the human whether the detail should
     become its own paper (the `paper_id` mechanism — a technical companion
     the main paper cites). Asking is not deferring: the decision stays with
     the human; you supply the honest estimate.
     **THE PROOF-STYLE SPEC — what to write, and what NOT to write.** The
     measured gap: an expert wrote a deep two-part lemma proof in ~1.6K chars;
     our renders of comparable content ran 10–15×. The difference is never
     the mathematics — it is CEREMONY. Put this spec verbatim into every
     rendering instruction you issue:
     - **Write inside the paper's standing conventions.** Never restate
       hypotheses or re-quantify objects the section's setup already fixes —
       one clause ("with notation as in Setup X") suffices. Fact-graph
       statements are fully self-quantified BY DESIGN; a rendered proof must
       NOT inherit that register.
     - **Prose first.** Manipulations flow inside sentences; display ONLY the
       one or two equations the reader must refer back to. A proof that is a
       chain of displayed equations is a computation log, not a proof.
     - **One proof, no ceremony.** Absorb sub-steps as sentences ("since …
       and …, it follows that …"). A new labeled lemma is justified ONLY when
       it is cited from ≥2 places or is genuinely independent — never one
       lemma per source fact.
     - **Mechanism, pivot, close.** Name what is computed, give the pivotal
       identity, conclude. Trust the competent reader for routine expansion —
       the verifier accepts mechanism+outcome for standard-type steps; what
       it rejects is a bare claim with NO mechanism.
     - **Calibration:** a deep lemma proof lands at 0.5–2K chars; if a single
       proof render exceeds ~4K, you ordered transcription — rewrite the
       instruction, not the budget.
     - **THE PIVOT IS NOT COMPRESSIBLE.** Mechanism+outcome is accepted for
       standard-TYPE steps ONLY. The argument's own NOVEL pivotal
       computation — the step that is this paper's contribution — must be
       DERIVED, not named (measured: two 2-page gap-fill sections were
       rejected at exactly their named-not-derived pivots, while every
       surrounding mechanism+outcome standard step was accepted). Budget a
       deep-gap SECTION at 2–3 pages / 6–10K: a 2–4K frame plus ~2–4K of
       actual derivation per pivot; a 1–2-page ask gets the frame right but
       forces the pivot into a bare name, which fails verification.
       **Deriving a pivot does NOT suspend the style spec** — the derivation
       is written like every other proof here: prose-first, one or two
       displays, standing conventions (the measured expert proof derived its
       pivot INSIDE 1.6K chars; deriving ≠ transcribing). If a derived pivot
       exceeds ~4K, the instruction ordered transcription — rewrite it.
       **And YOU name the pivots in the brief** — typically ONE step per
       section, the step that is that section's contribution; every step you
       did not name stays at mechanism+outcome. A writer left to guess which
       steps count will defensively derive everything — that is the
       transcription failure returning through the back door.
     - **Named anti-patterns** (put these in the instruction as prohibitions):
       requantification blocks; display-per-step; per-fact lemma-ization;
       "we now verify / recall that" scaffolding; restating definitions
       before use.
     **THE ONE EXCEPTION — stop and ask the human.** When you genuinely judge
     you cannot get it right; or two-to-three consecutive rounds on the SAME
     gap have produced no effective progress (verdict unchanged, findings not
     narrowing); or your edits are making the paper WORSE (regressions, new
     findings outpacing cleared ones, structure degrading) — STOP. Preserve
     the best state, and consult the operator with an honest account: what
     you tried, why it failed, and your best guesses. Grinding past that
     point burns budget and damages the paper; asking is the professional
     move, not a failure.
   Deliver honestly either way: report the verifier's verdict as it stands,
   with your triage attached (which findings you filled, which you classified
   standard-and-deferred) — never present a triaged-away finding as "passed".

   **THE TERMINAL STATE — "passes modulo trivial computations".** On a paper
   written from verified facts, expect the FIRST verify to yield mostly
   standard-type findings plus AT MOST one or two REAL structural gaps. Fill
   only those (each a small curated supplement — a support layer and a few K
   of expert-compressed writing), re-verify once, and you should be at a
   residual of ONLY standard-type/trivial findings. **That residual IS the
   successful end of the loop**: stop, report the verdict as it stands with
   the trivial-residual list, and hand the fill-or-not calls to the operator.
   Do NOT keep filling standard-type items to chase a clean binary verdict —
   that chase is precisely how a 40-page paper bloats into a monograph while
   the verifier's re-sampling keeps moving the target. **No goal overrides
   the triage** (the mirror of the length-freeze rule). If you find yourself
   in a fourth-plus revise round still filling, STOP and re-triage: you are
   over-filling.

   **THE QUALITY BACKSTOP — fewer gaps is not the goal; a better paper is.**
   Keep the TOTAL number of writing rounds small (the healthy trajectory:
   one curated write + small located fixes + at most one real-gap
   supplement). Across rounds, judge the PAPER, not just the findings count:
   if findings are going down but the paper is getting worse — narrative
   giving way to fact-stacking, structure fragmenting, length creeping — the
   loop is destroying value, and clearing more findings will not buy it
   back. STOP at once: preserve the best state, tell the human WHERE the
   writing difficulty is (which section, which kind of content, what you
   tried) and what guidance you need. And in ALL cases — success, stall, or
   stop — leave behind one final paper that is ELEGANT and carries an
   honest, located list of its remaining gaps, so a human knows exactly what
   is unproven and where. An elegant paper with known gaps is a deliverable;
   a gap-free fact-stack is not.

0. **FIRST — fed ≠ rendered: read what ACTUALLY landed, not your memory of what you
   sent.** Handing a fact to `paper_revise(add_facts=…)` does NOT mean its PROOF is in
   the paper. The reviser routinely renders the fact's **statement** as a lemma while
   its proof still **asserts** a step that the fact ITSELF delegates to a *deeper* fact
   ("by Fact X"). So before deciding what to send, do THREE reads: (a) the verifier's
   located finding — WHAT is flagged; (b) the reviser's **actual rendered proof** of
   that lemma in `main.tex` — what really landed; (c) the **source fact's own proof**
   in the fact graph. If that fact's proof discharges the flagged step by CITING a
   deeper fact, **that deeper fact (and its sub-chain) is the true missing chokepoint**
   — trace the `by Fact …` chain down to the fact whose proof actually *contains* the
   flagged computation, and feed that, **bottom-up** (a fact renders self-contained
   only once ITS predecessors are already rendered, so their `\ref`s resolve instead of
   becoming stripped assertions). Counting a fact "done" because you sent it once
   **under-counts the real depth** — its delegated sub-proof can be dozens of facts —
   and misattributes a *depth* gap to "reviser fidelity." (Measured example: the MatTan
   ω(S) degree-formula fact delegated to a 121-fact induction that was never rendered;
   re-sending the top fact could never close it.) Only when the fact's own proof
   CONTAINS the flagged step in full, yet the paper still asserts it, is it a genuine
   fidelity problem → step 1a.

1. If it concerns the re-rendering of a **verified fact** (the writer compressed or
   mangled a proof that was already verified), re-render it — but **instruct
   SYNTHESIS, never transcription**: resolve the theorem's `\label` → source fact id
   via `<paper>/.provenance.json`, read that fact's proof (and, per step 0, the
   sub-facts it delegates to) from `runtime/projects/<p>/fact_graph/facts/<id>.md`,
   and — this is YOUR judgment step — **name the argument's skeleton yourself** (its
   2–4 key steps) in the instruction you pass with the verified proof text to
   `paper_revise(notes=…)`. Ask for **ONE compact-but-complete proof at paper
   granularity, written as an expert author writes**: every claim carried by an
   actual argument (never a bare "by the same argument" / "a similar computation"),
   short steps written in full, standard-type sub-computations stated with their
   precise mechanism and outcome; **forbid one-lemma-per-fact transcription and
   helper-lemma sprawl**. The support-layer BINDING RULE applies INSIDE proofs too:
   you curate what the proof presents, the renderer writes it. Per-round `add_facts` follows the BINDING-RULE spirit: a small bottom-up set (~10-15 facts at most); several small rounds beat one dump.
1a. **If a compact synthesis is rejected, refine — do not jump to transcription.**
   The verifier rejects **bare assertions**, not compactness (measured on the same
   deep step: a human-expert 1.6K compact rendering passed independent expert
   review, while a per-fact transcription of identical content ran 28K — 17× — with
   helper-lemma sprawl; forced-transcription orders were the bloat source, and are
   how a paper degenerates from an article into an unreadable monograph). So on a
   re-flag: read WHICH mechanism the verifier says is missing, and instruct adding
   exactly that step — still synthesized, still one proof. If two such refinements
   fail, suspect your fact selection first (step 0: fed ≠ rendered — the real
   chokepoint may be a deeper delegated fact), and only as a LAST resort order a
   fuller write-out of the one specific step (never the whole chain), accepting the
   local bloat knowingly.
2. If it is genuinely new paper math (glue, a reduction, a combined argument), pass
   the located finding itself to `paper_revise(notes=…)` for a real fix — or, if the
   paper is missing a prerequisite, re-select facts / re-run `paper_write`.
3. Recompile (Stage 3) → re-run `paper_verify_math`. Keep the loop **bounded**
   (~5 rounds); on overrun stop and escalate to the operator with the ledger as the
   honest record. (The verifier is an LLM and has run-to-run variance — a `wrong`
   that flips to `correct` with no edit is that variance; the loop absorbs it, so
   never hand-mark the ledger to defeat the gate.)

**On `too_large` — YOU decompose; the tool never chunks.** `too_large` means the
assembled verifier input (role prompt + `REFERENCE_LEDGER` + the whole `main.tex`
body) exceeds `DANUS_PAPER_VERIFY_WHOLE_DOC_CAP` (default ~700K chars ≈ 175K
tokens): one codex call cannot hold the paper. The tool records the blocker
honestly and does **not** split — decomposition is a judgment call, so it is
yours:

1. **First** check whether the cap is just conservative: if the verifier model's
   context genuinely fits the prompt (`body_chars` in the envelope), raise
   `DANUS_PAPER_VERIFY_WHOLE_DOC_CAP` and re-run the tool. Done.
2. Otherwise decompose the paper **by its results — never by position in the
   text**. The verifier's contract is the constraint: it judges whether a
   document, read on its own, establishes **its main result** — so every part
   you send must BE such a document, culminating in a designated result. A
   sequential slice (consecutive pages or sections chosen for length) fails
   this: a middle slice culminates in nothing, and the verifier has no main
   result to judge. Instead, pick the paper's major results R1…Rn (the main
   theorem plus the big propositions it rests on) and build one part per
   result. Part k's input document is:
   - the paper's notation base: preamble macros + every Definition/Notation env;
   - the full **statements only** (no proofs) of the other designated results
     that part k's proofs rely on, presented as *"established elsewhere in this
     paper (separately verified)"*;
   - the complete development of R_k **as written** (its supporting lemmas and
     R_k itself, statements + proofs), ending at R_k — the part's own main
     theorem.
   Each part must stand on its own given those established statements — that is
   what "self-contained" means here — and sit comfortably under the cap. The
   part for the paper's main theorem takes the other designated results as
   established and closes the argument.
3. **Drive the verifier yourself**, mirroring the tool: read
   `agents/skills/write-paper/roles/PAPER_MATH_VERIFIER_PROMPT.md` (and
   `roles/AGENTS.md`), append the confirmed `REFERENCE_LEDGER.md` and the part
   document, and run a fresh `bin/codex exec --sandbox read-only` per part; read
   the final verdict JSON from its output. Every part must return `correct`. A
   `wrong` in the part for R_k → the revise loop above for those findings, then
   re-verify that part and every part that took R_k's statement as established.
4. **Clearing the gate:** the ledger still holds the `too_large` row and only the
   tool writes verdicts — so surface the per-part record (each part's scope,
   verdict, log) to the **operator**, and only on their explicit confirmation set
   the `whole-paper` row's status to `overridden` with a note pointing at that
   record. That is the operator-override channel `deliver_ok` accepts
   (`correct` / `trusted` / `overridden`). Never do this silently.

**Deliver is BLOCKED unless the whole-paper verification is `correct` or the
operator explicitly `overridden`** (the `deliver_ok` / `blockers` fields;
`paper_math_verify.deliver_ok` reads the ledger deterministically). **Override is
an operator per-paper policy (default mandatory-verify):** the operator may choose
to ship despite a still-failing or too-large verification — but it is then
**visibly flagged in the paper** (a `\note` / disclosure line), surfaced as a
fork, **never silent**. Set the ledger status to `overridden` only on the
operator's explicit call.

### 6. Deliver + (operator fork) push

Deliver the `main.tex` + `main.pdf` paths. **First confirm the deliver gate:** the
whole-paper math verification (Stage 5.5) must show `deliver_ok=True` (the
whole-paper verification `correct`, or an explicit operator `overridden`) — never
deliver a paper whose math was not re-verified
as written. **Pushing to a LaTeX git repo (e.g.
Overleaf) / posting to arXiv is outward — an operator fork** (your standing red
line: confirm anything that leaves the machine). `driver/latex_git_push.sh`
handles the push; if it lacks the repo URL / token, **ask the operator, store the
non-secret config in your own notes and the token in the gitignored secrets file**
(see the script header), then confirm before pushing.

## Default house style (configurable — lives in STYLE_GUIDE.md / PAPER_STRUCTURE.md)

The **non-negotiable** part is integrity, not typography: preserve the
mathematics, cite honestly, never fabricate a reference, leak no pipeline metadata
(the PRIME DIRECTIVE in `roles/AGENTS.md`). Everything else — document class
(`amsart` by default), `\epsilon`, the manual surname-sorted
`\begin{thebibliography}{99}`, manual `Theorem~\ref{}` cross-references, exact
citation numbers, the filler bans, and the acknowledgement disclosure — is the
**default** AMS-style house style. It lives in `STYLE_GUIDE.md` /
`PAPER_STRUCTURE.md`, is embedded into the codex by the tool, and is the
operator's to change (edit those files, or override per paper in
`PROJECT_BRIEF.md`). **You never apply it yourself** — you do not write LaTeX.

## Honesty (load-bearing)

State only what you verified. A paper is "produced" only after `compile_verify.sh`
passed (PDF, zero errors, no undefined citations) **and `paper_verify_math` shows
`deliver_ok=True`** (the paper re-verified `correct` as written, or an
operator `overridden`) — "it should compile" / "the facts were already verified" is
not confirmation (the paper re-stitches the facts, so it is re-verified as a
distinct artifact). If the auditor could not verify a reference, say so; do not
present an `unverified` bibliography as checked. Never claim a push succeeded unless
you confirmed it landed.

## Style maintenance (offline, operator-gated; the anchor preflight is stage 1a)

`roles/STYLE_DISTILLER_PROMPT.md` distills recurring rules from the operator's
own papers under `style/anchors/` into the unified `style/STYLE_GUIDE.md`, **as
proposals the operator accepts or rejects** — it never auto-applies an edit, and
it never touches any paper's `main.tex`. A bad distill would silently corrupt the
guide that governs every future paper, so the accept gate is mandatory.

It is **presence-triggered, once, operator-gated** (stage 1a above): it runs in
the preflight only when `anchors/` is non-empty AND stale (newer than
`style/.distilled_at`, or that marker is absent), so anchors an operator drops in
are distilled rather than silently ignored — but it never runs when `anchors/` is
empty or unchanged, and it is not part of the per-paper hot path (the writer
consumes the already-distilled guide). The operator may also run it by hand at any
time.
