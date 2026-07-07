# style/anchors/ — your own papers (the only place to add examples)

This skill ships **no example papers of its own** — bundling anyone's writing
would bias the house style toward one author or subfield. Instead, this folder is
the single, easy entry point for **your** material: drop in papers you have
written (or any writing whose style you want the output to resemble), and the
skill will both **imitate** them and **learn** from them. Empty by default; the
generic `../STYLE_GUIDE.md` + `../PAPER_STRUCTURE.md` still produce a complete
paper on their own.

## How to add your material

Make one folder per paper and put whatever you have inside it — **any files are
welcome**: LaTeX source (`.tex`, `.bib`, `.sty`, `.cls`), a compiled `.pdf`, even
notes. The `.tex` source is the most useful (the writer can copy preamble, macros,
and prose shape from it); a `.pdf` alone still conveys structure and voice.

```
anchors/
  my-paper-on-X/
    main.tex          # ideal: the arXiv/submitted source
    refs.bib          # optional
    my-paper-on-X.pdf # optional; useful when you have no source
  my-survey/
    survey.pdf        # a PDF on its own is fine too
```

No naming or format requirements beyond "one folder per paper". You do not need to
edit any other file — the skill discovers whatever is here.

## What the skill does with it

- **Voice, via distillation (the primary path).** The `STYLE_DISTILLER` role
  (`../../roles/STYLE_DISTILLER_PROMPT.md`) reads ALL these anchors and proposes
  recurring style rules to fold into `../STYLE_GUIDE.md` — as suggestions you
  accept or reject, never auto-applied. The writer then draws its **voice** from
  that one unified guide, so it benefits from every anchor at once (not just the
  "closest" one). The skill runs the distiller automatically in a preflight when
  this folder is non-empty and has changed since the last distill.
- **Structure, via one named exemplar (optional).** A paper's `PROJECT_BRIEF.md`
  may name ONE folder here in its `structural_exemplar:` field; the writer then
  imitates that single anchor's **structure** (preamble, macros, front-matter,
  section skeleton) — deterministically, chosen by the brief, never by the writer
  "picking the closest". Leave the field blank for none. Voice still comes from
  the distilled guide, not from this exemplar.

## Notes

- **Optional.** With this folder empty, the two generic guides still yield a
  complete, compilable paper; anchors only make the voice more like yours.
- **Local only.** Anchors are your inputs, not part of the shipped skill. Keep this
  directory out of any public commit (it is gitignored by default); an anchor's
  internal label must never leak into a produced paper as a `\cite{}`.
