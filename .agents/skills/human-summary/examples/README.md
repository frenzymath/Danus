# human-summary example — end-to-end smoke test

A minimal 3-fact toy project (`odd-sum/`) plus a sample report (`report.md`) so the
render pipeline is exercisable on a fresh clone without a real project.

## Layout

```
examples/
  odd-sum/
    PROBLEM.md                         # verbatim goal
    fact_graph/facts/*.md              # 3 verified facts (statement/proof/intuition)
  report.md                            # a human-summary artifact rendered from those facts
```

`odd-sum/` mirrors the real fact-graph layout (`<project>/fact_graph/facts/*.md`
with 6-field frontmatter, `<project>/PROBLEM.md`) that this skill reads. In a real
run the main agent reads that spine and *writes* a `report.md`; here `report.md` is
provided so you can test the renderer directly.

## Smoke test

Prerequisites: node (`scripts/bootstrap.sh`) and a headless Chrome/Chromium
(`DANUS_CHROME_BIN` or `google-chrome`). Check with:

```bash
bash ../doctor.sh
```

Render the sample report to PDF:

```bash
bash ../render_pdf.sh report.md /tmp/odd-sum-report.pdf "Odd-sum progress report"
# -> PDF -> /tmp/odd-sum-report.pdf (<N> bytes)
```

The mandatory id self-check must return nothing on a clean report:

```bash
grep -E '[0-9a-f]{16}' report.md    # exits 1 (no match) => clean
```
