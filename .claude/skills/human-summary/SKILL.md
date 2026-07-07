---
name: human-summary
description: Write a human-readable mathematical progress report (compiled PDF) on a project for the operator / the mathematician who posed the problem. This is NOT `elaboration` (dense input for the strategy consult) and NOT the dashboard. Render from the fact graph's verified statements/proofs into a clean, self-contained report — precise problem statement, essential partial results with REAL proof sketches, the one major obstacle, a neutral approach timeline, and the single remaining lemma written out in full — then output a compiled PDF.
---

# Human-readable progress report

You are the main agent. This skill produces a **human-facing** math report — for
the operator, or the mathematician who posed the problem. The audience is a
mathematician fluent in standard English math terminology who knows **nothing**
about how the work was produced.

You do **not** author the prose yourself and you do **not** read the fact files.
The report is written by an **isolated report-writer codex** behind the
`human-summary` MCP tool, which is fed ONLY the verbatim problem statement and a
**scrubbed, id-free bundle** of the project's verified results. That isolation is
the structural guarantee that no internal identifier (`fact_id`, `author`,
`predecessors`, …) or system/orchestration vocabulary can reach the report — the
author's window never contains any of it. Your job is to **call the tool, then
render and deliver the PDF.**

## Step 1 — generate the clean report.md (the tool does the writing)

Call the MCP tool (server `human-summary`):

```
summary_write(project="<project>")
```

It assembles the writer prompt + `PROBLEM.md` + a scrubbed fact bundle
(statement / proof / intuition bodies only — **all frontmatter stripped**, no fact
ids, no author names, no machinery), drives an isolated codex, writes the result
to `<project>/report/report.md`, and runs a **leak check** on the output. It
returns a small dict:

```
{report_md_path, status, returncode, leak_findings, stderr_tail}
```

**Honesty gate — do not proceed unless `status == "ok"`:**

- `status == "ok"` means: codex exited 0, produced a non-empty report, AND the
  leak check found **zero** hits (`leak_findings == []`). Only then does
  `report.md` exist as a clean artifact.
- `status != "ok"` (`error` / `timeout` / `leak`): **no clean `report.md` is
  written.** On a leak, the offending output is quarantined at `report.leaky.md`
  and `leak_findings` names what leaked — report this to the operator, do NOT
  render or deliver it, and do NOT hand-fix and pass it off as clean. If codex
  failed, surface `stderr_tail`.

You never read the fact graph and never write the report prose; the tool owns
both. If the operator asks for a different language/register, that is a property
of the writer prompt (`agents/skills/human-summary/REPORT_WRITER_PROMPT.md`,
operator-editable) — the register rule (narrative in the operator's language,
**all standard math terminology in English**) and the five-section structure are
locked there, not here.

## Step 2 — render the PDF and deliver

Once you have a clean `report.md`, render it to a self-contained PDF:

```bash
bash "${CLAUDE_SKILL_DIR}/render_pdf.sh" <report.md> <out.pdf> "Title"
```

This server-renders markdown + KaTeX into self-contained HTML and prints it to
PDF via **headless Chrome** — so the math + fonts are handled without any LaTeX
engine. **Deliver the PDF path** to the operator — never paste raw
`$...$`/`\boxed{}` into chat; it shows as tex garbage and is unreadable.

## Step 3 — backstop self-check (documented, kept as defence-in-depth)

The tool's leak check is the primary guard, and the scrub makes a leak
structurally impossible. As a belt-and-braces backstop before you deliver, you
may still grep the rendered source:

```bash
grep -E '[0-9a-f]{16}' <report.md>    # must return nothing (no fact_id / hash prefix)
```

If this (or the tool's `leak_findings`) ever fires, treat the report as
compromised: do not deliver it, and report the finding.

## What the report is (locked spec, enforced in the writer prompt)

For reference — you do not enforce these, the isolated writer does:

1. **Register / language.** Narrative in the operator's language; **ALL standard
   math terminology stays in English** (`reduction`, `coboundary`, `full-rank`,
   `saturation`, `negative twist`, `Green–Griffiths`, …). Math is identical across
   language versions; only the prose language changes.
2. **No identifiers / hashes** anywhere — results are rendered as statements, not
   pointed at by id.
3. **Content focus:** the essential partial results (each with a REAL, detailed
   proof sketch) + the one major obstacle; omit resolved-worry episodes.
4. **Fully self-contained statements** — every object introduced, every hypothesis
   quantified, every symbol defined.
5. **Five sections:** precise problem statement · main mathematical progress
   (proven / conditional) · main obstacle · neutral approach timeline · current
   status & the single remaining lemma written out in full (boxed).
6. **No numerical examples**; honest proven / conditional / conjecture marking.
7. **No system / operational info** — reads as a clean standalone research report;
   no fact counts, no consult/`master_guidance`, no swarm/worker/verifier
   vocabulary, blank author, no run timestamps.

## How this differs from `elaboration`

| | `elaboration` | `human-summary` |
|---|---|---|
| audience | the strategy consult (a machine) | a human mathematician |
| density | maximal, terse, status tables | readable prose + detailed proof sketches |
| ids | cites `fact_id`s | **none** |
| length | tight | as long as the math needs (multi-page is normal) |
| output | a global-memory entry (kind `elaboration`) | a compiled **PDF** |

Run `human-summary` **on demand** (the operator asks for a report) or periodically
as an operator update — it is separate from the strategy-consult cadence, and it
never feeds the consult nor reads/writes global memory as truth. It is also **NOT
`write-paper`**: no bibliography, no `external_refs`, no house style — a private
progress report, not a publication artifact.

## Prerequisites for the render (declare them; the ops layer provisions them)

- A **headless Chrome / Chromium** binary — resolved via `DANUS_CHROME_BIN` (from
  `scripts/env.sh`) or a `google-chrome` on PATH. This is a local PDF-render
  binary only; it is unrelated to any browser transport. Confirm with
  `bash "${CLAUDE_SKILL_DIR}/doctor.sh"`.
- **node** (provisioned by `scripts/bootstrap.sh`) + the pinned node deps
  (`markdown-it`, `katex`) in `package.json`. `render_pdf.sh` installs them once if
  absent; the KaTeX CSS is then vendored from the local install, so subsequent
  renders need **no network**.

A tiny 3-fact example under `examples/` exercises the render pipeline end to end.
