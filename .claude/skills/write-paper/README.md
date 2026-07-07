# write-paper

`write-paper` turns a project's **verified fact graph** into a **publishable LaTeX paper** — a
standalone `\documentclass{amsart}` source with a real, hand-written bibliography, compiled to a
clean PDF and ready for arXiv or a LaTeX git repo (e.g. Overleaf).

This is the human-facing setup doc. The agent reads `SKILL.md`; you read this. The skill is
field-neutral — it works for any area of mathematics and hardcodes no subject area, no named
theorems, and no real citations.

## What it produces

The skill does one thing: it writes the paper for a finished project. The mathematics comes **only**
from the project's verified facts — the agent never drafts theorems from its own memory — and the
bibliography is seeded from the structured references those facts already carry. The house style is a
generic, editable guide that ships with the skill, so you get a complete, compilable paper out of the
box; imitating your own past papers is an optional add-on, never required.

Everything lands in a per-paper workspace alongside the project's `fact_graph/` and
`global_memory/`. **A project can hold multiple papers** (one main theorem paper, a companion,
several theorems each written up on their own): every `paper_*` tool and `danus finalize` takes an
optional `paper_id`. The **default** paper (`paper_id` omitted or `"main"`) uses the **legacy**
paths `<project>/paper/` + `<project>/TARGET.md` (existing single-paper projects are unchanged);
any other `paper_id` gets an isolated `<project>/papers/<paper_id>/` workspace with its own brief,
ledger, `TARGET.md`, and `main.tex`, so papers never collide. There is **one fact graph per
project**; a paper's facts are just the transitive-predecessor closure of its own headline set (the
same closure the single-paper pipeline computes, rooted at that paper's target). The default
paper's workspace `<project>/paper/`:

- `main.tex` — the paper. One self-contained `\documentclass{amsart}` source, real `\ref`/`\cite`,
  a manual `\begin{thebibliography}{99}`.
- `main.pdf` — the compiled paper. Produced only after the compile gate passes (see Safety).
- `PROJECT_BRIEF.md` — per-paper framing (title, audience/venue, human authors, headline results,
  per-paper style overrides). Filled by a short interview, never invented.
- `REFERENCE_LEDGER.md` — the bibliography ledger, seeded from the facts' structured references and
  verified online by the reference verifier.
- `REVISION_LOG.md` — append-only history of revision rounds; each entry is the reviser's own
  round summary for that round, written by the tool.
- `.runs/` — per-call diagnostic run logs (gitignored). Each `paper_*` tool call writes one
  `<utc>-<tool>/log.md` capturing the full assembled prompt, codex's full stdout and stderr, the
  result, and the tool's decisions, and returns its path as `log_path` — for localizing a failure
  when a call comes back non-`ok`. Set `DANUS_WRITE_PAPER_RUN_LOG=0` to disable.

The agent seeds this folder the first time it runs, copying the files in `templates/` into their real
names and seeding the ledger from the facts.

## What you bring

The skill orchestrates the work but does not bundle the heavy machinery. Three things must be in place
before a run can finish:

- **A LaTeX toolchain.** A LaTeX engine must be on `PATH`. The compile gate
  (`driver/compile_verify.sh`) runs the engine and fails on any LaTeX error or
  undefined citation/reference; a `.tex` that does not compile cleanly is never
  delivered. Default engine is `pdflatex` (`xelatex`/`lualatex` via `TEX_ENGINE`).
  No TeX Live and no root? Set `TEX_ENGINE=tectonic` and run `bash
  scripts/install-tex.sh` — it installs **Tectonic**, a self-contained, perl-free
  engine (single static binary, downloads packages on demand) into `~/.local/bin`.
  The skill does not install LaTeX for you as part of bootstrap; it is a
  write-paper-only prerequisite.
- **A codex backend.** The heavy LaTeX drafting, revision, and audit reasoning is delegated to a local
  high-reasoning `codex`, driven by the `write-paper` MCP service (which delegates to
  the shared `danus.authoring.driver`). Point it at
  your backend with the `DANUS_CODEX_BIN` / `DANUS_WRITE_PAPER_MODEL` / `DANUS_WRITE_PAPER_EFFORT` environment
  variables (the per-service model/effort fall back to the neutral `DANUS_CODEX_MODEL` /
  `DANUS_CODEX_EFFORT`), or have a working `codex` on `PATH`.
- **Network access**, for the reference **verifier** (`reference_verify`). Verifying bibliographic data
  (authors, title, venue, year, arXiv id) against the literature needs to reach the network. The
  reference chain is: the auditor tool flags offline (no tools/network); the verifier tool then
  verifies each flag online and writes the ledger; the reviser applies the resulting fixes into the
  `.tex`. Offline, the verifier keeps any reference it cannot confirm flagged as `unverified` rather
  than guessing.

Optional: a repo URL and token if you want the deliver step to push outward (see Safety).

## How a run goes

You hand the project to the orchestrating agent and it drives the stages in `SKILL.md`:

1. Interviews you briefly to fill `PROJECT_BRIEF.md` (title, audience, human authors, headline facts).
2. Seeds `REFERENCE_LEDGER.md` from the facts' references.
3. Drafts `main.tex` with the writer, then runs the compile gate. It does **not** stop the worker swarm on its own — a partial result can be written up while the swarm keeps exploring; the main agent asks the operator whether to stop, and only then passes `stop_workers=True`.
4. Audits the references and revises as needed, recompiling each round.
5. **Re-verifies the whole paper as written** (`paper_verify_math`): the whole `main.tex`
   goes back through a dedicated paper-math verifier as ONE document, gating deliver on a
   durable `VERIFY_LEDGER.md`. The facts were
   verified individually, but the paper re-stitches them, so it is re-verified as a
   distinct artifact; the main agent drives a verify→revise loop until the
   verification is `correct` (or you explicitly override, which is then visibly
   flagged in the paper). A paper too long for one pass is decomposed by the main
   agent by results — each part a self-contained development culminating in a
   designated result — never sliced by position in the text.
6. Hands you the `main.tex` and `main.pdf` paths.

You stay in the loop for the decisions that are genuinely yours — author names, venue, and anything
that leaves the machine.

## Customising style

Two generic, plain-Markdown layers under `style/` control how the paper reads. You are encouraged to
edit both:

- `style/STYLE_GUIDE.md` — the **voice**: macro conventions, theorem and proof shape, citation and
  cross-reference rules, sentence-level style.
- `style/PAPER_STRUCTURE.md` — the **structure**: what each section contains, by length tier.

Both are field-neutral defaults: they name no subject area and use placeholders where a real paper
would name a concrete reference, so they apply to any area of mathematics.

**Optionally**, if you already have published papers, drop their `.tex` sources into `style/anchors/`
(one folder per paper). The writer then imitates — for structure only — the single anchor named in the
brief's `structural_exemplar` field; voice always comes from the distilled `STYLE_GUIDE.md`.
And the optional offline `STYLE_DISTILLER` role can later fold recurring patterns
from your anchors into `STYLE_GUIDE.md` as proposals you accept or reject. This is strictly an add-on.
**The `anchors/` directory is empty by default, and the two generic guides produce a complete,
compilable paper on their own** — anchors only make the output sound more like your own writing. See
`style/README.md`.

## Layout

This skill spans **two trees, split by reader**:

```
.claude/skills/write-paper/        # MAIN-AGENT side — Claude Code reads/runs this
  SKILL.md                       # the orchestration contract (the main agent reads this)
  README.md                      # this file (human-facing setup)
  driver/
    seed_ledger.py               # aggregate the facts' references into the starting ledger
    compile_verify.sh            # the compile gate: two pdflatex passes, hard fail on errors
    latex_git_push.sh            # OPTIONAL outward push to a LaTeX git repo (confirmed, operator-gated)
  templates/
    PROJECT_BRIEF.md.template    # seeds <project>/paper/PROJECT_BRIEF.md on first use
    REVISION_LOG.md.template     # seeds <project>/paper/REVISION_LOG.md on first use

agents/skills/write-paper/         # CODEX-facing side — embedded into the codex prompt by the
                                   # `write-paper` MCP (danus.write_paper); NOT read by Claude
  README.md                      # explains this half
  roles/
    AGENTS.md                    # the standing contract every role obeys (the PRIME DIRECTIVE)
    PAPER_WRITER_PROMPT.md       # writes the first complete main.tex
    PAPER_REVISER_PROMPT.md      # revises main.tex (compile fixes, editorial annotations)
    REFERENCE_AUDITOR_PROMPT.md  # verifies the bibliography; flags, never fabricates
    STYLE_DISTILLER_PROMPT.md    # OPTIONAL, offline: learns style from your anchors
  style/
    STYLE_GUIDE.md               # generic baseline — VOICE (edit to taste)
    PAPER_STRUCTURE.md           # generic per-section content plan — STRUCTURE (edit to taste)
    README.md                    # how to shape the style
    anchors/                     # OPTIONAL: your own exemplar papers (empty by default)
      README.md                  # how to drop in anchors
  boilerplate/
    acknowledgement.md           # automated-system disclosure (ON by default) + opt-in funding/thanks placeholders
  examples/                      # a toy end-to-end project (offline-test fixture + demo)
```

The split is by **who reads the file**: the main agent reads `SKILL.md` and runs
`driver/` + `templates/`; the paper codex never reads disk — the `write-paper` MCP
embeds the codex-facing `roles/style/boilerplate` into its prompt. So the
codex-facing half lives under `agents/` alongside the other codex agents (`worker`,
`verify`), not under `.claude/` (which is Claude Code's tree).

## Where it must live, and what it resolves at runtime

This skill is not a standalone package: it ships **inside the enclosing project
repository** and expects that repo's machinery to be present. Concretely,
`seed_ledger.py` imports the repo's fact-graph reader (the installed `danus.core`
package), the codex driving now lives in the installed `danus.authoring` package (the
shared one-shot isolated codex driver, used by both `danus.write_paper` and
`danus.human_summary`), driven by the `write-paper` MCP service (which reads
`DANUS_WRITE_PAPER_MODEL` / `DANUS_WRITE_PAPER_EFFORT` — falling back to the neutral
`DANUS_CODEX_MODEL` / `DANUS_CODEX_EFFORT` — and `DANUS_CODEX_BIN`, and calls the repo's `bin/codex`
wrapper), and the assembler reads the fixed role/style/boilerplate files from the
**codex-facing** half (located via `DANUS_WRITE_PAPER_SKILL_DIR`, default
`<repo>/agents/skills/write-paper`). Lifted out on its own, these dependencies
will not resolve; install it as part of the project.

Install the two halves at `<repo>/.claude/skills/write-paper/` (main-agent side:
`SKILL.md` + `driver/` + `templates/`) and `<repo>/agents/skills/write-paper/`
(codex-facing side: `roles/` + `style/` + `boilerplate/` + `examples/`).
`seed_ledger.py` locates the enclosing repository by walking a fixed number of
parents up from its own path
(`.../.claude/skills/write-paper/driver/seed_ledger.py`), and `bin/write-paper-mcp`
defaults `DANUS_WRITE_PAPER_SKILL_DIR` to the codex-facing half — so neither layout
is optional (or set `DANUS_WRITE_PAPER_SKILL_DIR` explicitly).

The project to write about is passed in per run as `<project>`. From the expected location the skill
resolves, per project:

- `<project>/PROBLEM.md` and `<project>/fact_graph/facts/*.md` — the verbatim problem statement and
  the verified facts the paper is built from.
- `<project>/paper/` — the default paper's workspace, seeded from `templates/` on first use; a
  non-default `paper_id` uses `<project>/papers/<paper_id>/` instead.

and from the install location:

- `seed_ledger.py` reads the project's fact graph through the repository's fact-graph reader;
- the `write-paper` MCP service (`danus.write_paper`) finds the repository's `codex` wrapper, or falls back to `codex` on `PATH`;
- `latex_git_push.sh` reads its repository URL and token from a gitignored secrets file.

The `style/`, `roles/`, `templates/`, and `boilerplate/` files are all read from the install location.

## Safety

- **Never fabricates.** Citations, authors, venues, years, and the mathematics all come from the fact
  graph or from verified sources. A reference the verifier cannot confirm stays flagged as `unverified`;
  an unclear proof step is marked `[GAP: ...]`, never smoothed over. No internal identifiers ever
  appear in the output.
- **The compile is a hard gate.** A `.tex` that does not pass `compile_verify.sh` — zero LaTeX errors,
  no undefined citations or references — is not considered done and is never delivered. "It should
  compile" is not a compiled paper.
- **Whole-paper math is a hard gate too.** The facts were verified individually, but the paper
  re-renders and re-stitches them, so it is a distinct artifact. `paper_verify_math` re-verifies the
  whole document, as written, through a dedicated paper-math verifier. Deliver is gated on a durable
  `VERIFY_LEDGER.md`: blocked until the verification is `correct` (or you explicitly override, which is
  then visibly flagged in the paper). A failed verify run is reported honestly — never mistaken for a
  paper that passed.
- **Pushing outward is a deliberate, confirmed step.** Posting to arXiv or pushing to a LaTeX git repo
  (e.g. Overleaf) leaves the machine, so it happens only on your explicit confirmation.
  `latex_git_push.sh` reads its repository URL and token from a gitignored secrets file and commits
  with a plain message (no automated-system co-author trailer).
