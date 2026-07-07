---
name: acknowledgement_boilerplate
description: "Generic, operator-configurable acknowledgement boilerplate added to a produced paper: an automated-system disclosure (on by default), a funding line, and personal thanks. Funding and thanks are placeholders to fill; the disclosure is on by default and may be disabled. Invent nothing."
---

# Acknowledgement boilerplate (operator-configurable)

This file is the paper-invariant acknowledgement block the writer adds to a
produced paper. The **automated-system disclosure (1) is ON by default**; the
**funding (2) and personal-thanks (3) blocks are opt-in placeholders**. The writer/
reviser copies in only what the operator has configured (in `PROJECT_BRIEF.md`
or at interview time) and never invents a name, a grant number, or an
affiliation. If a placeholder is left unfilled, leave it as a visible
`\note{[ack/blocker] ...}` flag rather than guessing.

Placement follows `style/PAPER_STRUCTURE.md` §5.7 and depends on the paper. The
neutral default is an unnumbered `\section*{Acknowledgements}` after the last body
section (or appendices) and before the bibliography. A first-page unnumbered
footnote, or — in a long, introduction-heavy paper — a final
`\subsection*{Acknowledgements}` at the end of the Introduction, are acceptable
alternatives when the operator's house style prefers one. Use a single, consistent
placement per paper; never emit two acknowledgement blocks.

## (1) Automated-system disclosure (ON by default; the operator may disable it)

A paper produced by this system **discloses** that fact by default: the system is
an automated, AI-driven proof-search and verification pipeline, and the
integrity-correct default is to say so plainly, in the open. The operator may turn
the disclosure off for a given paper, but the default is **ON**.

Name the system plainly — by default **"the Danus system"** (the public name of
this open-source project; a fork may substitute its own system name). The
disclosure names the system only; it never exposes an internal codename, a
development-team roster, a fact id, a hash, a file path, or any other internal
pipeline identifier (those remain forbidden — see `roles/AGENTS.md` PRIME
DIRECTIVE item 6).

Put the disclosure in **two to three visible places** — this is the whole point,
so it must be readable text, never a LaTeX comment (a comment discloses nothing):

- **Abstract** (last sentence):
  `The main result of this paper was obtained with the assistance of the Danus system, an automated proof-search and verification system.`
- **A Remark** near the acknowledgement (requires `\newtheorem{rem}[thm]{Remark}`):
  ```
  \begin{rem}
  The main result of this paper was obtained with the assistance of the Danus system, an automated proof-search and verification system.[SYSTEM CITATION] [VERIFICATION STATEMENT] Because automated systems have limitations, it is possible that we have missed related references in the literature, and we welcome comments from experts.
  \end{rem}
  ```
- **The acknowledgements section** (one sentence), when the operator prefers the
  disclosure to also live there.

`[SYSTEM CITATION]` is an OPTIONAL `\cite{...}` to a published description of the
system, included only if the operator supplies a real, verified reference. Never
fabricate one or hardcode an author list; omit it otherwise.

`[VERIFICATION STATEMENT]` is a placeholder the operator fills with a **truthful**
description of what was actually checked, and only if it is true — e.g. "The proof
was independently re-verified by the system's verifier." Do **not** ship the
re-verification claim by default: if the operator supplies no true verification
statement, omit that sentence (leave a `\note{[ack/blocker] verification statement?]}`
flag) rather than asserting a check that did not happen.

If the operator disables the disclosure for this paper, omit both the abstract
sentence and the Remark.

## (2) Funding line (placeholder)

The first acknowledgement sentence, when funding applies, is the funding
statement. Use the operator-supplied text verbatim; do not fabricate a grant
number or agency.

```
\section*{Acknowledgements}
[FUNDING ACKNOWLEDGEMENT]
```

`[FUNDING ACKNOWLEDGEMENT]` is replaced with the operator's exact funding
sentence (for example, "The author was partially supported by [GRANT]."). If
the operator says there is no funding to acknowledge, omit this sentence.

## (3) Personal thanks (placeholder)

After the funding line, append the operator-supplied thanks verbatim:

```
[PERSONAL THANKS]
```

`[PERSONAL THANKS]` is replaced with the operator's exact text (thanks to named
colleagues, hosts, referees, etc.). Names come only from the operator — never
from the system, the fact graph, or inference. If the operator gives no thanks,
omit this sentence.

## Notes for the writer/reviser

- The funding (2) and personal-thanks (3) blocks are configuration: add a block
  only when the operator has supplied its content. The automated-system disclosure
  (1) is **ON by default** — include it unless the operator disabled it for this
  paper.
- Never emit an internal codename, a development-team roster, a fact id, a hash,
  or any other pipeline identifier in the visible acknowledgement. (Naming the
  system itself — "the Danus system" — for the default disclosure is allowed; that
  is the public project name, not an internal identifier.)
- If the automated-system note is enabled but you have no published reference to
  cite for the system, do not invent a `\cite{}` or `\bibitem` for it — the note
  stands on its own without a citation.
