---
name: obtain-immediate-conclusions
description: Derive immediate mathematical consequences from a theorem statement or subgoal. Use when starting a new problem, branch, or subgoal, or when cheap progress or a cleaner reformulation is needed before deeper proof search.
---

# Obtain Immediate Conclusions

Extract direct implications before speculative reasoning.

## Input Contract

Read from memory and current context:

- `problem_id`
- current theorem/subgoal statement
- memory

## Procedure

1. Normalize notation and restate the claim in equivalent forms.
2. List direct consequences that follow from definitions and basic algebraic/logical manipulations.
3. Split consequences into necessary conditions and candidate sufficient conditions.
4. Mark each consequence with confidence and justification type.
5. For every conclusion, explicitly decide whether it is likely fragile and should be stress-tested by counterexample.
6. If a conclusion is fragile, record why it is fragile and indicate that `$construct-counterexamples` should be considered next.

## Output Contract

Publish each conclusion to global memory with `gm_add` (kind `conclusion`):
`claim` = the conclusion's statement, `evidence` = the derivation/justification
that makes it checkable, and carry these fields in the record:

```json
{
  "statement": "...",
  "justification_type": "by_definition|calculation|known_fact|logical_equivalence",
  "confidence": 0.0,
  "is_fragile": false,
  "fragility_reason": "",
  "suggested_followup": "none|construct-counterexamples",
  "scope": "global|branch|subgoal",
  "branch_id": "optional",
  "subgoal_id": "optional"
}
```

Rules:

- `is_fragile` must always be present.
- If `is_fragile=true`, then `fragility_reason` must explain the risk and `suggested_followup` should be `construct-counterexamples`.
- If `is_fragile=false`, use `fragility_reason=""` and `suggested_followup="none"`.

## Tools

- `gm_add` (publish the conclusion finding)
- `gm_search` (recall related findings across the swarm)
- `search_arxiv_theorems` for nontrivial consequences
- Codex built-in web search for background definitions/terminology

## Failure Logging

If no meaningful consequence is found, note it in your local memory (`events`) with:

- `event_type="immediate_conclusions_stalled"`
- missing assumptions and suspected blockers
