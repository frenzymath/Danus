# PAPER_STRUCTURE — the per-section content plan, organized by length tier

This is the **structure** companion to `STYLE_GUIDE.md` (which governs *voice*).
It says **what each part of a paper contains** and **how the paper is organized**,
as a function of the paper's length. It is deliberately **field-neutral**: it names
no subject area, bakes in no area-specific notation or reference set, and uses
placeholders (e.g. *"the standard reference(s) for the area"*) wherever a real
paper would name something concrete. The LaTeX conventions it references
(document class, theorem environments, bibliography form) are `STYLE_GUIDE.md`'s
**configurable defaults for an AMS-style mathematics paper**, not universal
requirements — a different venue or subfield may change them.

A `PROJECT_BRIEF.md` per-paper rule, or an operator-supplied anchor under
`style/anchors/`, may override anything here — except the non-negotiable floor in
`STYLE_GUIDE.md` §0 and the PRIME DIRECTIVE in `roles/AGENTS.md`, which always
hold. Nothing in this file relaxes them.

**How to use this file.** First pick a **length tier** in §1. Then follow that
tier's recipe — §2 (note), §3 (mid), or §4 (long) — top to bottom; each recipe
walks the whole paper in order. The recipes reference one shared block of
conventions in §5 (front-matter, abstract rules, statement promotion, proofs,
bibliography) that holds across tiers, so a writer who has chosen a tier reads one
linear plan plus a common appendix.

---

## 1. First decide the length tier

The whole structure follows from this one early choice. Pick by the *shape of the
verified content* — the number of headline results, the depth of the predecessor
DAG of the load-bearing facts, and how much standing machinery the proofs share —
**not** by a target page count.

| Tier | When |
| --- | --- |
| **note** (§2) | one headline result (or one result plus an immediate corollary); a shallow proof DAG; little shared machinery; the argument is short and self-contained. |
| **mid** (§3) | one main theorem with several genuine supporting lemmas, or two related headline results; enough shared notation to deserve a preliminaries section; a proof that decomposes into a handful of body sections. **The default tier when in doubt.** |
| **long** (§4) | several headline results (often lettered); a deep DAG; substantial shared machinery several sections inherit; reductions or intermediate frameworks that each earn a section. |

When two tiers seem equally plausible, choose the **smaller** one and let a section
grow, rather than padding a short argument into a long skeleton. Record the chosen
tier in the round summary.

---

## 2. Tier: a short note (top-to-bottom recipe)

A note is lean. It earns trust by reaching the result quickly and proving it
without ceremony.

1. **Front-page elements** — §5.1.

2. **Abstract** — §5.2. One to three sentences. A single clean headline result can
   warrant **one sentence**. A three-paragraph abstract on a one-theorem note is a
   smell.

3. **Introduction — one short section, no subsections.** `\section{Introduction}`
   is one context paragraph that motivates the problem and places it against prior
   work (citing the standard reference(s) for the area), followed **immediately** by
   the main statement promoted to a numbered `\begin{thm}` (promotion rules, §5.3).
   A note usually needs no roadmap; if it runs to two body sections, one clause
   suffices.

4. **Notation, inline.** A note rarely needs a standalone preliminaries section. Fix
   the few standing conventions in a short paragraph at the start of the body (or at
   the end of the introduction), citing the standard reference(s) for the area for
   anything assumed. Promote to a real `\section{Preliminaries}` only if the
   conventions exceed a paragraph (then follow §3 step 4).

5. **The body — one or two sections.** State the result (or restate the promoted
   introduction theorem with the **same label**) and prove it (proof architecture,
   §5.4). A small supporting fact becomes an inline `Claim` proved on the spot; a
   supporting fact large enough to deserve its own statement becomes a `\begin{lem}`
   immediately before the main proof. Section openers, §5.6.

6. **Acknowledgements** — §5.7. Only if the operator supplied content; otherwise
   omit the section entirely.

7. **Bibliography** — §5.8.

---

## 3. Tier: a mid-length paper (top-to-bottom recipe)

The default tier: one main result with real supporting lemmas, or two related
results, with shared machinery deserving its own section.

1. **Front-page elements** — §5.1.

2. **Abstract** — §5.2. Three to five sentences: the headline result(s) in words,
   one sentence of context, one on the shape of the proof or the new ingredient.

3. **Introduction — no formal subsections; bolded thematic block-headers.** Chunk
   the introduction with bolded headers, each followed by its discussion and the
   relevant statement, in this order:

   ```
   \section{Introduction}

   \medskip
   \noindent\textbf{<Theme / context>}.
   [Context and prior work; cite the standard reference(s) for the area as a
    roll-call cluster (§5.8) where a framework is introduced, not a token cite.]

   \medskip
   \noindent\textbf{<Theme of the main result(s)>}.
   [Discussion specific to the headline.]
   \begin{thm}\label{thm:...} ... \end{thm}     % promoted; see §5.3

   \medskip
   \noindent\textbf{Method.}  % or "Outline of the proof"
   [One short paragraph naming the main steps and key intermediate statements,
    with forward Theorem~\ref{}/Lemma~\ref{} references.]
   ```

   With two co-equal results, state both (two numbered theorems, or the lettered
   convention if that reads cleaner; §5.3). Close with a one-paragraph roadmap, one
   sentence per section, when the paper has more than two body sections. Each
   introduction block opens with a reader-orienting sentence and, when
   multi-paragraph, closes with a signal sentence.

4. **Preliminaries / Notation — its own section (§2 of the paper).** A single
   `\section{Preliminaries}`; promote to `\section{Notation and conventions}` only
   when notation is unusually heavy.
   - **Open by fixing the ground.** First adopt the standard references and
     terminology for the area (cite the area's standard reference(s); hardcode
     none), then state the ambient setting — base setting / category / standing
     assumptions. The ambient-setting statement lives **here**, not in the
     introduction.
   - **Cite-or-define rule.** Material covered by the standard references is assumed
     without re-derivation; objects beyond that level are **defined** here (in
     `\begin{defn}`) or earlier if used in the introduction. Do not redefine
     standard notions; do not assume non-standard ones.
   - **Setup is an environment, not a section.** Hypotheses several later statements
     inherit go in a `\begin{setup} … \end{setup}` block referenced by label, not a
     separate section.
   - **Topic-named subsections** (`\subsection{<topic>}`), not the "Preliminaries on
     <topic>" prefix pattern. Short proofs only — one- or two-line reductions and
     quoted prior-work statements; substantial proofs belong in body sections.

5. **Body sections — in dependency order.** Order so each result is stated after
   everything it depends on, following the predecessor DAG: preparatory lemmas
   first, then the section(s) building the key intermediate statement, then the
   section proving the main theorem (often `\section{Proof of <result>}`). Each
   section opens per §5.6. Statements are promoted per §5.3 and proved per §5.4.
   Restate a headline theorem promoted in the introduction at its body home with the
   **same label**, under a brief "We now prove Theorem~\ref{thm:main}." opener.

6. **Acknowledgements** — §5.7.

7. **Bibliography** — §5.8.

---

## 4. Tier: a long multi-result paper (top-to-bottom recipe)

Several headline results, a deep DAG, and substantial shared machinery. Built on
the mid recipe with the expansions below; walk it top to bottom.

1. **Front-page elements** — §5.1.

2. **Abstract** — §5.2. Four to eight sentences across one to three short
   paragraphs: each headline result in words (or the umbrella result plus "As an
   application, we also prove …"), one or two sentences of context, one on method.

3. **Introduction.** A common and effective layout for this tier — **one
   acceptable option, not a requirement** — is a two-tier split with lettered
   theorems: `§1 Introduction` carries the headline results as **lettered**
   theorems (`Theorem A`, `Theorem B`, … via a separate `alphthm` counter), and a
   following section (named for what it does — e.g. applications of the main
   results and a sketch of the proofs) carries the precise/technical numbered
   versions plus the proof sketches. A single well-organized introduction that
   states the headline results and defers their technical forms to the body is
   equally acceptable; choose by what the material needs. When you do use the
   two-tier split, lay §1 out in this order:

   ```
   \section{Introduction}\label{sec:introduction}

   \subsection*{Background}
   [Context, history, motivation, multi-paragraph; roll-call citation clusters
    (§5.8) for each framework invoked.]

   \subsection{<First headline result>}
   [Motivation specific to this result.]
   \begin{alphthm}[<accessible-English title>]\label{thm:...} ... \end{alphthm}
   [Comparison with prior work, with exact citations (§5.8).]

   \subsection{<Second headline result>}
   ...

   \subsection*{<Secondary result>}
   [Announced with its statement, but not given a numbered subsection.]

   \subsection*{Roadmap}          % only when there are several lettered results:
   [a small diagram of the logical implications among the headline theorems]

   \subsection*{Sketch of the proof of the main results}
   [Multi-paragraph proof sketches with forward \ref{}s.]

   \subsection*{Structure of the paper}
   [One short paragraph outlining the later sections — one sentence per section,
    covering preliminaries and any appendix.]

   \subsection*{Acknowledgements}  % optional placement — see §5.7
   ```

   **Numbering rule:** a *numbered* `\subsection{}` is reserved for **headline
   results only** (one lettered theorem + motivation + comparison). **Everything
   else** in §1 — Background, secondary results, Roadmap, Sketch, Structure,
   Acknowledgements — is an *unnumbered* `\subsection*{}`. When in doubt, use
   `\subsection*{}`.

4. **Preliminaries / Notation — one or more sections.** As in §3 step 4, but with
   substantial shared machinery, split into a notation/conventions section and one
   or more "recalled framework" sections, each citing the standard reference(s) for
   the area for what is recalled and clearly marking recalled versus new. Put
   hypotheses inherited by many later statements in a named `\begin{setup}`
   referenced by label thereafter; reserve a setup *section* for the rare paper
   whose multiple headlines share one common reduction.

5. **Body — staged in dependency order, possibly grouped into parts.** Order from
   the bottom of the DAG upward: foundational lemmas, then each intermediate
   framework or reduction in its own section, then a section per headline result.
   When the paper is long enough, group sections into Parts. A reduction section
   states the equivalence first, then reduces (`STYLE_GUIDE` §4 — no "WLOG"). Each
   section opens per §5.6 with a one-sentence statement of its role. Promoted
   lettered theorems are restated at their body homes with the **same labels**.

6. **Appendices**, if any: self-contained material that would interrupt the main
   line (a technical computation, a recalled construction, an auxiliary result).
   Place after the last body section, before acknowledgements; label `sec:` like any
   section and reference by `Appendix~\ref{...}`. Put nothing load-bearing for a
   headline result in an appendix unless the brief asks for it.

7. **Acknowledgements** — §5.7. Place per the neutral default there (after the
   body, before the bibliography); if this paper's house style instead keeps the
   acknowledgement at the end of the Introduction, it becomes the final
   `\subsection*` of §1 (shown in the layout above).

8. **Bibliography** — §5.8.

---

## 5. Shared conventions (all tiers)

These hold across every tier; each recipe above references them by number. Form
detail lives in `STYLE_GUIDE.md`; this is placement and content.

### 5.1 Front-page elements

`\title{...}` from `PROJECT_BRIEF.md`. Author block from the brief — real names and
affiliations if the operator supplied them, neutral placeholders if they declined
(never fabricate an author, affiliation, or grant number). `\subjclass[2020]{...}`
and `\keywords{...}` present. `\date{}` left empty unless the operator wants a date.
These are the operator's data, not the writer's to invent.

### 5.2 Abstract

A short, reader-facing summary — **not** a content artifact (it may paraphrase; it
is the one place exempt from the preserve-all-math floor). One paragraph (or up to a
few short ones in the long tier), no environments, no `\ref{}`, **no `\cite{}`**.

- **Lead with the result.** Open `We prove that …` or a close variant (`We
  establish …`, `We show …`, `We determine …`, or a sharp declarative when the
  result is quantitative). **Never** open with `In this paper, we …`.
- **Paraphrase over symbols.** State the result in words; admit only unavoidable
  light notation (a number-system symbol, a dimension, a numeric value). Anything
  heavier is paraphrased.
- **Credit goes in the introduction, not here.** A bare "answering a question of
  [name]" is allowed only when the credited question is genuinely part of the
  headline.
- **Present tense**, with past tense only for a prior-work context sentence. Close
  with `As an application, we …` when applications exist and do not distract from a
  dominant headline; otherwise omit. Length scales with tier (§2-§4).

### 5.3 Statement placement and environment promotion

- **Render every result from its fact-graph source**, fully quantified and
  self-contained; preserve hypotheses, conclusions, and displayed content exactly.
  No naked symbols in any statement (`STYLE_GUIDE` §3).
- **Placement.** A headline result may be *promoted* into the introduction as a
  numbered (note/mid) or lettered (long) theorem and restated at its body home with
  the **same label**, so `\ref` resolves to one number. Ordinary supporting results
  are stated once, in the body, where their hypotheses are available.
- **Choose each result's environment by the role the fact plays** (every claim is
  promoted to a labeled environment — `STYLE_GUIDE` §8): `thm` for a headline or
  self-standing result; `prop` for a substantial result mainly serving the
  headline; `lem` for a step reused across proofs or extracted for clarity; `cor`
  for an immediate consequence; `defn`/`setup` for definitions and inherited
  hypotheses; `rem` for a non-load-bearing observation. Promote a fact from inline
  `Claim` to a numbered `lem` once it is referenced more than once or is long
  enough to obscure the proof it sits in.
- **External inputs** used as black-box ingredients are each stated as their own
  labeled environment citing the original source — not bundled into an enumerated
  list. Lettered headline statements are reserved for the long tier or for a mid
  paper with two or more genuinely co-equal results.

### 5.4 Proofs

Proof **form** — architecture choice (cohesive / multi-step / extracted-lemma),
`\noindent\textbf{Step N.}` markers, proving embedded claims immediately, reduction
phrasing, one-claim-per-sentence justification — is `STYLE_GUIDE` §4. **Placement:**
each proof sits at its result's body home, in predecessor-DAG order (§5.6).

### 5.5 Preliminaries and standing machinery

The preliminaries section (mid and long tiers) is the single home for standing
conventions and recalled material: definitions in `\begin{defn}`, symbol conventions
in a notation environment, inherited hypotheses in a `\begin{setup}` referenced by
label thereafter. Recalled (not re-proved) results carry a citation to the standard
reference(s) for the area and are clearly marked as recalled. A note folds this into
an inline paragraph (§2 step 4). No length target — the section is exactly as long
as the paper needs.

### 5.6 Body-section order and openers

- **Order.** Sections follow the predecessor DAG of the load-bearing facts: a result
  appears only after everything it depends on. Across a paper this yields
  preliminaries → setup/reductions → preparatory lemmas (grouped by theme) →
  intermediate framework(s) → headline proof(s) → optional further discussion or
  appendix.
- **Openers.** Every body section opens with a one-sentence preview of what it does
  (`In this section, we prove …` or `The goal of this section is to prove …` —
  rotate between the two across a long paper), connecting to what came before and
  what it feeds via `\ref` rather than "as before" or "the previous step"
  (`STYLE_GUIDE` §7). A body section needs no closing prose summary — the last
  `\end{proof}` is the closer, and the next section follows.
- **No standalone "Scope" section.** Put limitations or scope in a `Remark` attached
  to the relevant result, not under a bureaucratic header.

### 5.7 Acknowledgements

**Placement.** In the note and mid tiers, an unnumbered section
(`\section*{Acknowledgements}` or `\subsection*`) after the last body section /
appendices and before the bibliography; an alternative first-page unnumbered
footnote is fine if the operator prefers. In the long tier, the final
`\subsection*{Acknowledgements}` **inside the introduction** (§1), immediately
before the next `\section`; if an input draft places it at the end, relocate it.

**Content** is drawn from the blocks in `boilerplate/acknowledgement.md`: the
on-by-default automated-system disclosure, plus an operator-supplied funding
sentence and personal thanks when given. Every name, grant
number, and affiliation comes from the operator — invent none; omit the section
entirely if the operator configured no blocks.

### 5.8 Bibliography and citation granularity

**Placement/content:** the bibliography is built **only from the verified
reference ledger** — no fabricated entries, and it lists only references the
paper's facts actually cite. All bibliography and citation **form** — the manual
`\begin{thebibliography}{99}`, `\bibitem[KEY]{KEY}` keys and surname sort, citation
granularity (`\cite[Theorem~1.5]{Key}`), roll-call clusters, replacing a stale
external cite with an internal `Theorem~\ref{...}`, and never leaking a style-anchor
label as a `\cite{}` — is `STYLE_GUIDE` §5 (and the §0 leak floor).

---

End of structure plan.
