---
name: search-math-results
description: Find program-conditioned math results, constructions, examples, counterexamples, analogies, and background references. Use when the current active program needs repair, mutation, analogy, a program shift, or carefully gated obstruction search.
---

# Search Math Results

Use this skill as the default retrieval workflow for mathematical background and related results, conditioned on the live research program currently being pursued.

## Input Contract

Read:

- the current target statement, subgoal, lemma, or claim
- the `program_stage`, chosen from:
  - `fresh_orientation`
  - `active_program`
  - `mature_subproblem`
- the current `active_program`, meaning the live research program currently being pursued, such as a construction route, globalization route, mutation route, or other proof strategy
- the current `missing_mechanism`, meaning the specific mechanism, construction, lemma, bridge, or proof move that is missing
- the `search_mode`, chosen from:
  - `repair`
  - `mutation`
  - `analogy`
  - `program_shift`
  - `theorem_level_blocker`
- the search intent:
  - `theorem`
  - `construction`
  - `example`
  - `counterexample`
  - `background`
- relevant branch/subgoal context from memory

If the prompt explicitly declares the `program_stage`, `active_program`, `missing_mechanism`, or blocker policy, obey those declarations. If the prompt does not declare the stage, default to `fresh_orientation` for a new problem, first-pass search, or no mature program yet; use `active_program` when the run already has a live named program, branch, or missing mechanism; and use `mature_subproblem` only when the run is already narrowed to a repeatedly failed mature subproblem or mature active program.

## Search Modes

- `repair`: search for results or constructions that directly repair a specific missing step in the current active program.
- `mutation`: search for nearby constructions or variants that modify the current active program while preserving continuity with it.
- `analogy`: search broadly, including in apparently unrelated areas, for mechanisms, lemmas, constructions, examples, or proof ideas that might transfer to the current missing mechanism after translation or modest modification.
- `program_shift`: search for a genuinely new program after repeated failure of the current one, while explaining the possible splice point or bridge back to the current problem.
- `theorem_level_blocker`: search for obstruction or impossibility results only under the activation rule below.

`theorem_level_blocker` is not a default mode. It is disallowed by default in `fresh_orientation`. It is allowed in `mature_subproblem` when the blocker search targets that narrowed mature subproblem or mature active program rather than the whole original goal. It is also allowed whenever the prompt explicitly asks for obstructions, impossibility results, blocker theorems, or negative evidence. If blocker mode is not allowed, downgrade to `repair`, `mutation`, `analogy`, or `program_shift`.

Broad and creative search is allowed. Do not restrict yourself to the surface vocabulary of the current problem or only the literal keywords in the prompt. Cross-field and apparently unrelated analogy search is acceptable when it targets the same missing mechanism. Theorem-level, proof-level, theory-level, and more abstract analogy search are all allowed when tied to a plausible transfer idea.

## Procedure

1. Identify the current `program_stage`, `active_program`, `missing_mechanism`, and `search_mode` before searching.
2. For non-blocker modes, usually generate searches in multiple layers. In `fresh_orientation`, allow broad object-level, theorem-level, proof-pattern, and theory-pattern queries. In `active_program` and `mature_subproblem`, still allow broad queries, but tie them to the active program or a plausible program shift.
3. Start with `search_arxiv_theorems`.
4. When using `search_arxiv_theorems`, phrase the query as a complete mathematical statement whenever possible, but also issue mechanism- and analogy-driven queries when they better target the missing mechanism. Each hit carries `title`, the full verbatim `theorem` text, `arxiv_id`, and the in-paper `theorem_id`; use `arxiv_id` to pull the exact paper.
5. Inspect the returned items and decide whether they are useful for the current active program.
6. Do not use broad recursive scans of `downloads/` as a theorem-search engine. If an exact local paper/file is already known or prompt-recommended, read that exact path. Otherwise search externally first. If relevant long-term papers already exist in `downloads/common`, prefer those exact files before re-downloading.
7. If a genuinely new technical branch is opened (a new class of objects, a new construction regime, or a new body of machinery), then before killing that branch normally do at least one of the following: download and read at least one exact paper about that direction; read an exact local paper already present in `downloads/common` or another exact prompt-recommended path; or explicitly justify why no extra literature layer is needed because the branch has already reduced to a previously audited regime.
8. External search first is still the default, but once a genuinely new direction is chosen, exact paper download/read is expected before final branch rejection. This rule is about depth of engagement with a new direction: use a small number of exact relevant papers, not no papers and not many-paper rummaging.
9. Keep all downloaded PDFs and extracted text files organized inside `downloads/` in the current working directory.
10. If a useful theorem/example/counterexample is found and it comes from a paper, download that paper into the workspace, extract its text, and read the extracted text before relying on the result.
11. If a useful theorem is found, do not stop at the statement alone. Read the proof of that theorem as well and extract any techniques, constructions, reductions, or proof patterns that may help with the current target statement.
12. Expand the definitions and concepts appearing in that theorem using the surrounding context of the paper, and check carefully whether the theorem is actually applicable to the current situation. Be explicit about terminology that may shift across contexts. If the theorem is only a partial result for the current target, also analyze why its method does not prove the full statement — which extra hypotheses it needs, where the proof breaks without them, and what obstruction this reveals (do not merely force the current object to satisfy the extra hypotheses).
13. Record not only what the theorem says, but also what its proof suggests for the current active program and missing mechanism.
14. If the theorem search returns no useful information, switch to Codex's built-in web search.
15. Use the built-in web search either to look for specific math results or to gather background information, terminology, standard references, canonical constructions/examples/counterexamples, or remote analogies.
16. If the built-in web search reveals a useful paper, again download it, extract its text, and read the relevant extracted text before using it in reasoning.
17. If the built-in web search reveals a useful theorem, also read its proof, expand its local definitions from the paper context, and extract the techniques that look adaptable to the current active program. Apply the same partial-result analysis if the web result is only a partial result.
18. Summarize the most useful findings and explain why they matter for the current proof state.
19. If a result may later be used in a proof, preserve its full statement and source identifiers (`title`, `authors`, `arxiv_id`, `theorem_id`, year) so downstream proof steps can cite it explicitly — and so it can be passed as a structured `external_refs` entry when the proof that uses it is submitted via `fact_submit`.

## Usefulness Test

For `fresh_orientation`, treat search results as useful if they do at least one of the following:

- provide a theorem/lemma/definition close to the target statement
- provide a construction/example/counterexample that can be adapted
- suggest a standard technique or reformulation relevant to the current branch or problem
- provide a proof-level analogy
- provide a theory-level analogy
- provide a remote analogy together with a plausible transfer idea

For `active_program`, treat search results as useful if they do at least one of the following:

- repair a concrete missing mechanism in the active program
- provide a mutation of the current program
- provide a remote analogy that can plausibly transfer
- provide a new program together with a plausible splice point or bridge to the current problem
- provide a proof-pattern or theory-pattern transfer hypothesis that could plausibly be migrated into the active program

For `mature_subproblem`, use the `active_program` criteria and additionally allow gated blocker search.

A result can be strategically useful even if it does not yet directly repair the missing mechanism, provided it includes a plausible transfer hypothesis explaining how its construction, proof, or theory might transfer.

Treat results as not useful if they are vague, merely generic survey material, or a whole-goal obstruction search when blocker mode is not allowed. If the results are too weak to guide the next step, fall back to the built-in web search.

## Output Contract

Note a summary of the search in your local memory (`events`) — search is process,
not a shared finding. (A *useful reference you actually use* is recorded inside the
proof step that cites it, with its complete statement + `paper_id`/`theorem_id`/
`arXiv id`.) Summary record:

```json
{
  "event_type": "search_math_results",
  "query": "...",
  "program_stage": "fresh_orientation|active_program|mature_subproblem",
  "active_program": "...",
  "missing_mechanism": "...",
  "search_mode": "repair|mutation|analogy|program_shift|theorem_level_blocker",
  "blocker_search_allowed": false,
  "usefulness_tier": "direct|strategic|discard",
  "analogy_depth": "theorem|proof|theory|meta",
  "transfer_hypothesis": "optional plausible transfer idea; analogy_depth is descriptive bookkeeping, not a ranking of importance",
  "new_direction_requires_exact_paper": false,
  "literature_depth_reached": "none|local_exact|downloaded_exact",
  "search_intent": "theorem|construction|example|counterexample|background",
  "primary_tool": "search_arxiv_theorems",
  "fallback_used": false,
  "splice_point": "optional bridge back to the current problem",
  "results_summary": ["..."],
  "useful_references": [
    {
      "title": "...",
      "complete_statement": "...",
      "url_or_id": "...",
      "paper_id": "...",
      "arxiv_id": "...",
      "theorem_id": "...",
      "local_pdf_path": "optional",
      "local_text_path": "optional",
      "expanded_definitions": ["paper-context expansions of terms/concepts used in the statement"],
      "applicability_check": ["why the statement does or does not apply in the current setting"],
      "partial_result_analysis": ["if only a partial result: extra hypotheses, where the method fails for the full problem, and what difficulty this reveals"],
      "proof_insights": ["optional extracted techniques or ideas from the proof"],
      "why_useful": "..."
    }
  ],
  "branch_id": "optional",
  "subgoal_id": "optional"
}
```

## Tools

- `search_arxiv_theorems` (Matlas arXiv theorem search — verbatim statements)
- `gm_search` (check whether a sibling already found/used this result)
- Codex built-in web search (fallback when the theorem search is too weak)
- local memory (`events`) for the search log — direct file write

## Failure Logging

If neither theorem search nor web search yields useful information, note in local memory (`events`):

- `event_type="search_math_results_stalled"`
- the attempted queries
- the reason the results were not useful
