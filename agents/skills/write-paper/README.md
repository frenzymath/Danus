# write-paper — codex-facing prompts & style (embedded by the `write-paper` MCP)

These are the **codex-facing** fixed files for the paper roles. They are **not**
read by the main agent (Claude Code), and **not** symlinked into a codex home the
way `agents/skills/worker` / `agents/skills/verify` are. Instead the **`write-paper`
MCP service** (`danus.write_paper`, launched by `bin/write-paper-mcp`) reads them
at call time and **embeds them verbatim into the one-shot codex prompt** — the
paper codex runs in an empty cwd and reads nothing from disk.

Located via `DANUS_WRITE_PAPER_SKILL_DIR` (default `<repo>/agents/skills/write-paper`).

- `roles/`       — `AGENTS.md` (the PRIME DIRECTIVE) + the writer / reviser / auditor / verifier / style-distiller role prompts, plus the `PAPER_PLANNER` + `PAPER_SECTION_WRITER` prompts used only when a too-large closure is written section-by-section (see below)
- `style/`       — `STYLE_GUIDE.md` (voice) + `PAPER_STRUCTURE.md` (per-section plan) + `anchors/` (optional operator exemplars)
- `boilerplate/` — `acknowledgement.md`
- `examples/`    — a toy end-to-end project used as the offline-test fixture + a worked demo

**These files are agent-facing runtime inputs, embedded verbatim into the codex
prompts** — keep developer/architecture orientation OUT of them and put it here
instead. The role map, for developers:

- `PAPER_WRITER_PROMPT.md` — writes the first complete `main.tex` from the brief,
  the ledger, and the fact-graph math.
- `PAPER_REVISER_PROMPT.md` — revises an existing `main.tex` (compile failures,
  citation fixes, operator annotations, gap-fill).
- `REFERENCE_AUDITOR_PROMPT.md` — offline; flags bibliography entries it cannot
  vouch for, never fabricates.
- `REFERENCE_VERIFIER_PROMPT.md` — online; verifies the auditor's flagged
  citations (arXiv + web); the tool writes the confirmed ledger rows. The online
  half of the auditor→verifier→reviser chain.
- `PAPER_MATH_VERIFIER_PROMPT.md` — the whole-paper math verifier. Deliberately a
  THIRD verifier, separate from the fact-submission verifier (`danus/verify`) and
  the reference verifier: it trusts confirmed citations and re-checks the paper's
  own reasoning as written. Its policy affects paper delivery only, nothing
  upstream.
- `STYLE_DISTILLER_PROMPT.md` — offline; distills style rules from
  `style/anchors/` into `style/STYLE_GUIDE.md`. Never auto-applies.

The **main-agent-facing** half of this skill — the recipe `SKILL.md`, the scripts
the main agent runs (`driver/`), and the `templates/` it instantiates — lives under
`.claude/skills/write-paper/`.

**Chunked (section-by-section) generation.** When a target closure's full-proof
writer prompt would exceed the model context window, the MCP auto-chunks (threshold
`DANUS_PAPER_WRITE_CHUNK_CHARS`): a `PAPER_PLANNER` pass (closure STATEMENTS ONLY →
fixed preamble/front matter + a section plan covering every closure fact + the
bibliography), then one `PAPER_SECTION_WRITER` call per section (that section's full
proofs + the fixed macros/labels + other results' statements for `\ref`), then a
deterministic Python stitch. Each call is still a non-agentic isolated codex; the
single-pass path is unchanged when the closure fits. See
`.claude/skills/write-paper/SKILL.md` Stage 2.
