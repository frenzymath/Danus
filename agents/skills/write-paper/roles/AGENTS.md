# AGENTS.md — the standing contract for the paper agent

This is the role-agnostic contract every `write-paper` codex role reads first. It states
the rules that hold no matter which role is running. The role-specific prompts in
this folder add to it; they never relax it.

## 0. PRIME DIRECTIVE — preserve all math and citations; leak no pipeline metadata

Binding on every role. If you cannot satisfy any of items 1–6, emit a
`\note{[prime/blocker] <reason>}` flag in the output — never silently violate.

1. **Every mathematical assertion in the input is preserved.** Hypotheses,
   definitions, intermediate steps, sub-lemmas, calculations, conclusions. When
   the input is an elaborated draft, the prose itself encodes math content, so
   compressing prose = omitting math. Style edits do not authorize content
   compression. The one exception is the ABSTRACT, which is a reader-facing
   summary and is paraphrased, not a content artifact.

2. **Every citation is preserved AND every reference is properly cited.**
   - No weasel substitution: never replace `\cite{Key}` with "well-known", "by a
     standard fact", "by Theorem X" (no key), "[Author]'s theorem" (no key), "the
     literature", "by classical results". If you cannot resolve a key, leave the
     existing `\cite{...}` or flag `\note{[cite/blocker] ...}`.
   - No narrative author-year prose in the body: every reference to a published
     result uses `\cite{Key}` syntax. The abstract is the only place with no
     `\cite{}`.

3. **No fabricated bibliography.** Never invent authors, title, venue, year,
   pagination, arXiv id, or DOI. Unverifiable entries stay flagged, never faked.

4. **LaTeX preamble is preserved.** `\documentclass{amsart}` by default (with an
   optional `geometry` block); honor a different class when the brief or the input
   names one. Every package and macro already in the input preamble
   (`hyperref`, `\definecolor`, custom `\newcommand`, `\theoremstyle`,
   `\DeclareMathOperator`) is preserved verbatim. You may ADD a missing package;
   never silently DROP one.

5. **Editorial macros are neutral and locked.** `\edit{}`, `\note{}`, `\todo{}`
   are defined in the preamble, never dropped, never made no-ops. Do not invent
   person-named editorial macros.

6. **No leaked pipeline internals (disclosure is the one intended exception).**
   Never write an internal codename, a fact id, a blueprint identifier, a long hex
   hash, a file path, a development-team roster, or a fabricated system bibkey in
   the title, abstract, body, author block, or bibliography — those are leaks. The
   single intended appearance of the automated system is the operator-configured
   **disclosure** (`boilerplate/acknowledgement.md` block 1): a clean statement,
   on by default, that the paper was produced with the help of the system, named
   plainly (e.g. "the Danus system"). That disclosure is deliberate and is not a
   leak. Any other internal tracking goes in HTML comments `<!-- ... -->` only.

**Compliance check before declaring done:** re-read items 1–6, scan the output
once for each, and either confirm compliance or insert `\note{[prime/blocker]
...}` flags.

## Hard constraints (apply to every role)

- **Style source is `style/STYLE_GUIDE.md`** (plus `style/anchors/` exemplars).
  Do not import style from unrelated files.
- **No reference fabrication.** When you need a citation you cannot verify, leave
  a `\note{[cite/blocker] ...]}` flag. The auditor verifies; it never invents.
- **Every paper carries an `\author{}` block.** Preserve every author present in the input verbatim. If the brief names the authors, use exactly those. If neither the input nor the brief supplies authorship, emit a neutral placeholder (`\author{Author}`) rather than omitting the block, and flag `\note{[author/blocker] no author supplied}` so the operator fills it in. Never invent a person, affiliation, or email, and never let a pipeline/system codename appear as an author value.
- **No git; no pushing outward on your own.** A role does not run `git commit`, `git push`, `git branch`, `git checkout`, or any other git command, and it never publishes the paper outward (arXiv, a LaTeX git remote) by itself. Sending the paper outward is a deliberate, operator-gated step run through the configured push driver (`latex_git_push.sh`, driven by the `LATEX_GIT_*` environment) — not something a role triggers as part of writing or revising.
- **The compile gate is law.** A `.tex` that does not pass `compile_verify.sh`
  (zero LaTeX errors, no undefined citations/references) is not done.
- **Honesty.** State only what you verified. "It should compile" is not a
  compiled paper; an `unverified` bibliography is not a checked one.

## When in doubt

Re-read the relevant role prompt top-to-bottom and flag uncertainty via
`\note{[*/blocker] ...}` rather than guessing.
