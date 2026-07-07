# PROJECT_BRIEF — odd-sum (toy example)

> Per-paper intent and constraints. Filled through a short interview with the
> operator (the write-paper skill asks; you do not invent answers). The math
> comes from the fact graph — this file is about framing, audience, and the
> per-paper overrides, NOT the mathematics.
>
> Everything below is synthetic placeholder data for the example.

## Title / working title
The Sum of the First $n$ Odd Numbers

## Audience & venue
A general mathematical audience; an introductory note-length venue. Target:
arXiv `math.HO`, mirrored to the synthetic journal *J. Example Math.*

## Authors & affiliations
- A. Author, Department of Example Studies, Example University (a.author@example.edu)
- B. Coauthor, Institute for Placeholder Mathematics (b.coauthor@example.org)

(All names, affiliations, and emails are obviously-synthetic placeholders for
this example.)

## Scope: what this paper claims
Headline result: `fact_odd_sum_main` — for every integer $n \ge 1$, the sum of
the first $n$ positive odd numbers equals $n^2$. Supporting lemmas:
`fact_odd_recurrence` (the partial-sum recurrence) and `fact_square_recurrence`
(the recurrence for squares). Note length; one theorem with two short lemmas.

<!-- STRUCTURED FIELDS (machine-read by the write-paper skill — keep the
     `field: value` shape on its own line; the prose above is for humans). -->

## Target results (headline facts)
headline_fact_ids: fact_odd_sum_main

The paper is written from the transitive-predecessor closure of this target
(here: `fact_odd_sum_main` plus its two predecessor lemmas — i.e. all three
facts), and the reference ledger is seeded from the same closure.

## Structural exemplar (optional)
structural_exemplar:

(No anchor supplied for this example; the generic PAPER_STRUCTURE.md note tier
supplies the structure. Voice comes from the unified STYLE_GUIDE.)

## Per-paper style overrides (override the global STYLE_GUIDE for THIS paper only)
None. Follow the global STYLE_GUIDE and the note tier of PAPER_STRUCTURE.

## Deadline / status
No deadline. Illustrative final draft for the example.

## Notes
- Tier: **note** (one headline result plus two immediate supporting lemmas).
- Automated-system disclosure: ON by default (name "the Danus system"). No
  funding and no personal thanks were supplied, so omit both of those
  acknowledgement blocks.
- No verification statement was supplied, so the disclosure Remark omits the
  re-verification sentence.
