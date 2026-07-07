# style/ — the house style for write-paper

This directory holds the two generic, editable layers the `write-paper` pipeline
applies, plus `anchors/` — the one place to add your own papers.

## The two generic layers

- **`STYLE_GUIDE.md` — voice (binding).** A compact, generic house-style guide for
  a publishable mathematics paper: macro architecture, theorem statements, proofs,
  citations and bibliography, cross-references, sentence-level style, environments,
  and an anti-pattern list. The §0 floor (preserve all math, cite honestly, never
  fabricate references, no pipeline leakage) always holds.
- **`PAPER_STRUCTURE.md` — structure (binding).** The per-section content plan:
  what each part of the paper contains and how the paper is organized, by length
  tier (note / mid / long). Field-neutral — it names no subject area and uses
  placeholders where a real paper would name a concrete reference or setting.

Both are plain Markdown. Neither names an author or a field; they are the
defaults the writer and reviser follow when no operator-specific style is
configured.

This skill ships **no example papers of its own** — bundling anyone's writing
would bias the house style toward one author or subfield. The only examples come
from *you*, via `anchors/` (below).

## How the operator can shape the style

1. **Edit the two guides directly.** Add, tighten, or override rules to match your
   own preferences. Keep them compact.
2. **(Optional) Drop your own papers under `style/anchors/`.** The single BYO entry
   point: one folder per paper, containing whatever you have — `.tex` source
   (ideal), a `.pdf`, or any files. The writer imitates the closest match's
   preamble, macros, front-matter, and prose shape; the `STYLE_DISTILLER` role can
   later distill recurring rules from your anchors into `STYLE_GUIDE.md` as
   proposals you accept or reject. See `style/anchors/README.md`.

## Layout

```
style/
  STYLE_GUIDE.md      # generic baseline — voice (edit to taste)
  PAPER_STRUCTURE.md  # generic per-section content plan — structure (edit to taste)
  README.md           # this file
  anchors/            # the only place to add examples: your own papers (empty by default)
    README.md
```

**With an empty `anchors/`, the two generic guides produce a complete, compilable
paper on their own.** Anchors only make the output sound more like your own
writing.

## Style maintenance (optional, offline, not in the hot path)

`roles/STYLE_DISTILLER_PROMPT.md` is an optional offline tool — useful only when
you have supplied anchors and want the guide to drift toward your voice. It
distills style rules from the anchors into `STYLE_GUIDE.md` as proposals, never
auto-applies them, and never runs during paper production. The skill is fully
functional without ever using it.
