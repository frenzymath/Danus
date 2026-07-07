# STYLE_GUIDE — house style for a mathematics paper

This is the **generic baseline** house style the `write-paper` pipeline writes
to. It contains no author-specific anchors and quotes no specific paper.

Read it in two layers:

- **§0 is the non-negotiable floor** — the integrity rules (preserve the
  mathematics, cite honestly, never fabricate a reference, leak no pipeline
  metadata). These live in the role contract (`roles/AGENTS.md`, the PRIME
  DIRECTIVE) and **always** hold, independent of any field, venue, or preference;
  §0 below only points there.
- **§1 onward are the default house style for a mathematics paper** — concrete
  typographic and structural conventions (document class, macros, theorem/proof
  shape, citation form). They are sensible **defaults**, not universal law: they
  assume an AMS-style mathematics article, and a different venue or subfield may
  legitimately want others. They are **configurable** — edit this file, or override
  per paper.

The operator may edit this file to encode their own preferences, and may drop
gold-standard exemplar papers under `style/anchors/` for the writer to imitate
(see `style/README.md`). Where an anchor or a `PROJECT_BRIEF.md` per-paper rule
is more specific than a default here, the more specific one wins — except the §0
floor, which always holds.

---

## 0. Non-negotiable floor

The integrity floor — **preserve all mathematics and invent nothing; preserve and
properly `\cite` every reference; fabricate no bibliography; leak no internal
pipeline identifier** (the automated-system disclosure in
`boilerplate/acknowledgement.md` is the one intended exception) — is the **PRIME
DIRECTIVE in `roles/AGENTS.md` (items 1–6)**, binding on every role. It always
holds, even against an anchor or a per-paper override. It is stated once, there,
and not repeated in full here so the two cannot drift.

---

## 1. Document class and preamble

These are the defaults for an AMS-style mathematics article; a `PROJECT_BRIEF.md`
override or a different venue's class may replace them (the §0 floor still holds).

- `\documentclass{amsart}` by default (11pt or 12pt acceptable). A `geometry` block
  for margins is fine. Use the venue's class when the brief names one.
- Preserve every package and macro already present in the input preamble
  (`hyperref`, `\definecolor`, custom `\newcommand`, `\theoremstyle`,
  `\DeclareMathOperator`, package options). You may ADD a missing package; never
  silently DROP one.
- Theorem environments via `amsthm`: a shared counter
  (`\newtheorem{thm}{Theorem}[section]`, then `\newtheorem{lem}[thm]{Lemma}`,
  `prop`, `cor`, `defn`, `rem`, `conj`, etc.). Use `\theoremstyle{plain}` for
  results and `\theoremstyle{definition}`/`remark` where appropriate.
- First-page elements: `\subjclass[2020]{...}` and `\keywords{...}` present;
  `\date{}` left empty unless the operator wants a date.

## 2. Macro architecture

- Define a canonical macro set in the preamble and use it consistently:
  `\mathbb`, `\mathcal`, `\mathbf`, `\mathfrak` shorthands and
  `\operatorname{}` / `\DeclareMathOperator` for multi-letter operators. Do not
  hand-typeset a multi-letter operator in plain italics.
- `\epsilon` always; never `\varepsilon`.
- `\colon` for the colon in a map `f\colon X\to Y`; `\mid` for the bar in
  set-builder notation; `\setminus` for set difference.
- Editorial macros are neutral and locked: `\edit{}`, `\note{}`, `\todo{}` for
  in-draft annotations. Define them in the preamble; never drop them and never
  define them as no-ops. Do not invent person-named editorial macros.

## 3. Theorem statements

- A theorem statement is fully quantified and self-contained: every symbol it
  uses is defined before it, defined inline right after, or forward-referenced.
  No naked symbols.
- Use `Let`, `Suppose`, and `Assume` for distinct roles, consistently: `Let $X$ be ...` introduces a fresh object (variable, space, map); `Suppose that ...` opens a proof by contradiction or a case-split assumption; `Assume that ...` states a standing hypothesis inside a theorem statement or a side hypothesis inside a proof.
- Theorem titles (the bracketed `[...]` argument) are in accessible English,
  with no symbol-only prefix. When restating a known result, the title cites the
  predecessor.
- Use lettered statements (`\begin{thm}` labelled A, B, ...) for headline
  results in the introduction when the paper has several; number ordinary body
  results.
- State hypotheses and conclusions as displayed lists (`enumerate`) when there
  are several; keep one logical clause per item.

## 4. Proofs

- Choose deliberately between a cohesive prose proof, a multi-step proof, or an
  extracted-lemma cluster, by the length and structure of the argument.
- Do not dispatch a proof with `by the same arguments`, `by similar arguments`, or `by standard arguments`. Either spell the argument out or extract the shared content as a lemma. A pointer of the form `the proof is similar to that of [Cite], with the substitution: ...` is acceptable only when the argument is verbatim after a single explicit substitution and reproducing it would require copying a long external proof; the substitution must be made explicit.
- For a multi-step proof, open with a one-paragraph setup, then
  `\noindent\textbf{Step N.}` steps; each step opens with a one-sentence preview
  of what it establishes.
- Prove an embedded `Claim` immediately where it is stated; do not defer it.
- Reductions read `Possibly replacing $X$ with $Y$, we may assume that ...`,
  with the equivalence stated first. Do not write "WLOG" or "without loss of
  generality".
- One mathematical claim per sentence. Each non-obvious assertion is justified
  by a formula, an internal `\ref`, or a `\cite` — never by an unsupported
  adverb.
- `Note that` / `Notice that` / `Observe that` may draw attention to a fact, but the fact must still be justified — it is an immediate consequence of something already stated or cited, is followed by a brief justification, or is the conclusion of a displayed calculation. Drawing attention is never a license to skip the proof.

## 5. Citations and bibliography

- Manual `\begin{thebibliography}{99}` with hand-written `\bibitem[KEY]{KEY}`
  entries (amsalpha-like keys); **no BibTeX**. Sort entries by author surname,
  not by the label string.
- Many-author keys use the `[Abc$^+$YY]` superscript-plus form.
- Cite at the right granularity: for a specific claim from a book or long paper,
  cite the theorem/proposition/chapter number, e.g. `\cite[Theorem~1.5]{Key}`.
- When a result has both an originating reference and a later proof, cite both
  with their roles clear.
- Replace a stale external citation with an internal `Theorem~\ref{thm:...}`
  once the result is proved internally (keeping genuine credit attribution).
- A Background paragraph that introduces an established framework carries a
  roll-call citation cluster (a handful of references) rather than a single
  token cite.
- Never let a style-anchor code (an exemplar's internal label) appear as a
  `\cite{}` in the paper.

## 6. Cross-references

- Manual `\ref{}` with a capitalized, typed type word and a tie:
  `Theorem~\ref{thm:foo}`, `Lemma~\ref{lem:bar}`, `Section~\ref{sec:baz}`.
- Never `\cref`, `\Cref`, `\autoref`, or `\hyperref` for cross-references.
- Equations: `\eqref{eq:foo}` (which already prints the parentheses); never
  write `Equation~\eqref{...}`.
- Label consistently by type: `thm:`, `lem:`, `prop:`, `cor:`, `defn:`, `eq:`,
  `sec:`, `fig:`, `table:`.

## 7. Sentence-level style

- Compact sentences, roughly one mathematical claim each. Prefer short.
- No em-dashes.
- Avoid filler and false-rigor adverbs: *clearly, obviously, trivially,
  straightforward, evidently, of course*. If a step is easy, either show the
  one line or cite it; if it is not, do not claim it is.
- Avoid vague register verbs in implication contexts: *we infer, we demonstrate,
  produces/produce* (as logical implication), *for brevity* (in proof prose),
  *one has*. Prefer *we prove, we show, it follows that, hence, therefore*.
- Vary consequence connectives (`Thus`, `Hence`, `Therefore`, `So`) rather than repeating one; rotating also helps avoid LaTeX bad line breaks. Reserve `In particular` for consequences that are genuinely a punchline or carry independent interest; for routine consequences use `As a consequence` or no connector. Use `Indeed` only to introduce explanatory or contextual elaboration, never as a one-line stand-in for a proof step.
- The abstract opens with `We prove ...` or a close variant (not "In this paper,
  we ..."), carries no `\cite{}`, and keeps notation to at most `$\mathbb{Q}$` /
  `$\mathbb{R}$` / numerics — anything heavier is paraphrased into words.
- Replace handwave phrases ("the machinery", "the previous step", "as before",
  "in the obvious way") with a formula, a citation, or a forward reference.

## 8. Environments and structure

- An Introduction that orients the reader: context, the headline statement(s),
  their relation to prior work, and a short roadmap. Each introduction
  subsection opens with a reader-orienting sentence and, when multi-paragraph,
  closes with a signal sentence.
- A Preliminaries / Notation section collecting standing conventions, set up
  once and referenced thereafter.
- Definitions in `\begin{defn}`; notation in a notation environment; setups that
  several later statements inherit in a `\begin{setup}`-style environment.
- Every construction, lemma, proposition, theorem, definition, or corollary lives in its own labeled environment with a `\label`, never as bare prose or a bold paragraph header. Promote based on a section's primary mathematical content, not its title: if a section's job is to prove one claim, state that claim as a labeled `\begin{lem}`/`\begin{prop}`/`\begin{thm}` at the top, then give the proof. The reason is referenceability — a later section can only cite a result that has an environment and a `\label`; bare prose cannot be `\ref`'d.
- Figures/tables: float with `[!htbp]`, a tight `fig:`/`table:` label, a
  one-sentence caption ending in a period; prefer TikZ for diagrams.

## 9. Anti-patterns (do not do these)

- Compressing or paraphrasing away mathematical content under the guise of style.
- Dropping or downgrading a citation to a weasel phrase; narrative author-year
  attribution in the body.
- A fabricated or unverified `\bibitem` treated as published; right title with
  wrong/guessed authors; invented venue, year, pagination, or arXiv id.
- `\varepsilon`, em-dashes, `\cref`/`\autoref`, BibTeX, `Equation~\eqref{...}`.
- Naked symbols in a headline statement; symbol-prefixed theorem titles.
- Filler adverbs standing in for justification.
- A bibliography sorted by label string instead of by author surname.
- Any internal pipeline identifier, codename, fact id, or hash in visible output.

---

End of style guide.
