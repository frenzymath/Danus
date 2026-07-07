# Example: fact graph → paper

A tiny, fully synthetic end-to-end example showing what the `write-paper`
pipeline consumes and what it produces. Everything here is a **toy**: the
mathematics is elementary and field-neutral, and every name, venue, and
citation is an obvious placeholder. Nothing in this directory is real data.

## What it demonstrates

The skill turns a project's **verified fact graph** (never the model's memory)
into a publishable LaTeX paper. This example shows that flow on the smallest
possible project:

```
project/                          INPUT — a toy "project"
  PROBLEM.md                      the verbatim goal
  fact_graph/facts/*.md           verified facts (statement / proof / refs)
  paper/PROJECT_BRIEF.md          per-paper framing (operator's data)

expected_main.tex                 OUTPUT — an illustrative paper the
                                  pipeline would produce from those facts
```

The toy goal: **the sum of the first $n$ positive odd numbers equals $n^2$**.
Three facts build it:

- `fact_odd_recurrence` — a one-step recurrence for the partial sums.
- `fact_square_recurrence` — the corresponding recurrence for $n^2$.
- `fact_odd_sum_main` — the headline identity, by induction, using the two
  recurrences as `predecessors`.

## How it maps to the pipeline

| Pipeline stage (see `../../SKILL.md`) | Artifact here |
| --- | --- |
| Source of content: the fact graph | `project/fact_graph/facts/*.md` |
| Verbatim goal | `project/PROBLEM.md` |
| Stage 0 — PROJECT_BRIEF (interview) | `project/paper/PROJECT_BRIEF.md` |
| Stage 1 — seed the reference ledger | run `seed_ledger.py` on `project/` (see below) |
| Stage 2-5 — write / compile / audit / revise | `expected_main.tex` (illustrative result) |

The fact files match the format `driver/seed_ledger.py` and the fact-graph
reader expect exactly: YAML frontmatter (`fact_id` / `problem_id` / `author` /
`predecessors` / `glossary_introduces` / `external_refs`) followed by
`## statement`, `## proof`, and an optional `## intuition`. The `external_refs`
field is a one-line JSON array of `{key, authors, title, year, ...}` objects —
the structured bibliography the seeder aggregates so citations come *from the
source*, not re-mined from prose.

### Try the first stage

From a checkout where the skill can import the `danus.core` package (see the skill
README on dependencies), seeding the ledger from these facts:

```bash
python3 ../../driver/seed_ledger.py project/ --out /tmp/REFERENCE_LEDGER.md
```

aggregates the two synthetic references below into `unverified` rows — the
starting point the reference auditor would then check.

## The two synthetic references

Both are deliberately fake placeholders (clearly-synthetic authors, a
made-up venue, no real arXiv id):

- `[AC24]` — A. Author and B. Coauthor, *A note on telescoping sums*,
  J. Example Math. (2024).
- `[Exm20]` — C. Example, *Elementary induction, revisited*,
  Example Lecture Notes (2020).

They resolve to `\bibitem`s in `expected_main.tex`; every `\cite` in that file
points at one of them, and the paper carries the on-by-default disclosure that
it was produced with the assistance of the Danus system.
