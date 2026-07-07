---
name: construct-toy-examples
description: Generate and analyze simpler examples that satisfy both the assumptions and the conclusion of a theorem statement or subgoal. Use when you are stuck in reasoning and need simpler examples to regain traction, or when you want to see where the assumptions take effect and gain intuition.
---

# Construct Toy Examples

Use this skill when the agent is stuck in reasoning and needs simpler examples that satisfy both the assumptions and the conclusion in order to understand why the statement works.

## Input Contract

Read:

- current statement/subgoal
- relevant `immediate_conclusions`
- relevant `counterexamples` and failed branch notes
- relevant background/results when available

## Procedure

1. Construct simpler cases (low degree, small dimension, special forms, canonical objects).
2. Ensure the toy example satisfies all assumptions of the target statement or subgoal.
3. Check that the conclusion also holds in the toy example.
4. Study where each assumption takes effect and what mechanism makes the conclusion true.
5. Identify repeated patterns, invariants, or proof ideas suggested by the example.
6. Use search/reasoning/decomposition as needed to find examples or simplify the situation.

## Output Contract

Publish each toy example to global memory with `gm_add` (kind `example`):
`claim` = what the example shows, `evidence` = the construction, plus these fields:

```json
{
  "example": "...",
  "why_relevant": "...",
  "assumptions_satisfied": ["..."],
  "conclusion_verified": true,
  "where_assumptions_take_effect": "...",
  "observed_pattern": "...",
  "supports_branch_ids": ["optional"],
  "subgoal_id": "optional"
}
```

## Tools

- `gm_add` (publish the example finding)
- `gm_search` (recall related findings)
- `search_arxiv_theorems` for matching examples/known motifs
- Codex built-in web search for known example families and standard constructions
- use `$search-math-results` when broader retrieval is needed

## Failure Logging

If generated examples are inconclusive, append an `events` record:

- `event_type="toy_examples_inconclusive"`
- include attempted example families
