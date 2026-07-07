---
name: direct-proving
description: Screen a decomposition plan by first trying to prove all of its subgoals directly, then identifying the key stuck points if the plan does not fully go through. Use when a decomposition plan is created.
---

# Direct Proving

Use this skill to screen decomposition plans by first trying to carry the whole plan through, and if it does not fully go through, then identify the key stuck points.


## Input Contract

Read:

- one decomposition plan from `subgoals`
- relevant `immediate_conclusions`, `toy_examples`, `counterexamples`, and `failed_paths`
- relevant search results and references
- any previously identified external statements whose proofs may be adaptable

## Procedure

1. Take one decomposition plan at a time.
2. For each subgoal, actively use the searched results, toy examples, and counterexamples that are most relevant to that subgoal.
3. When a similar theorem has been found, try to adapt its proof idea, construction, or reduction to the current subgoal instead of treating it as a black-box citation.
4. If the adapted theorem is only a partial result with extra hypotheses, first analyze why its method needs those hypotheses and where it fails for the current subgoal — do not skip this by merely trying to show the current object satisfies the extra hypotheses and applying the partial result directly.
5. First attempt to prove all subgoals in that plan directly.
6. Try to carry the whole plan through before switching into failure diagnosis mode.
7. For each subgoal, record whether it is:
   - already solved directly
   - partially advanced
   - blocked
8. If a subgoal is blocked or you get stuck on it, FIRST invoke `$construct-counterexamples` for that subgoal — test whether it is false, too strong, or missing hypotheses (not merely hard). If no counterexample emerges and the subgoal still resists after at least two genuine direct attempts, do not grind indefinitely: record the stuck point as an `obstacle`/`dead_end` finding (`gm_add`) so siblings skip it and the next round's `master_guidance` can bring fresh direction.
9. If a proof adaptation attempt fails, identify why the migration fails. Be concrete: for example, note which hypothesis is missing, which construction does not transfer, which step breaks, which counterexample blocks the migration, or which part of the searched proof depends on structure absent in the current setting.
10. If a subgoal is solved with a self-contained partial result that the rest of the plan will USE downstream, partial-verify that result with `$verify-proof` in partial-candidate mode before treating it as established. Adopting unverified partial results as building blocks is the single biggest correctness risk; the verifier is the sole authority on whether the partial result really holds.
11. If all subgoals are solved directly AND the partial results that compose into a full proof have each been partial-verified as needed, mark the plan as solved and assemble the proof draft.
12. If the plan does not fully go through, then identify the key stuck points as concretely as possible.
13. Focus on locating the decisive failure modes of the plan after this first full attempt, not on polishing a full proof.

## Output Contract

Publish one record per attempted subgoal to global memory with `gm_add` (kind
`proof_attempt`): `claim` = the subgoal + its status, `evidence` = the attempt /
the partial proof if solved, plus these fields:

```json
{
  "plan_id": "...",
  "attempt_type": "direct",
  "subgoal": "...",
  "attempt_summary": "...",
  "status": "solved|partial|stuck",
  "used_examples": ["..."],
  "used_counterexamples": ["..."],
  "counterexample_search_for_stuck_subgoal": {
    "performed": true,
    "summary": "...",
    "result": "refuted|not_refuted|inconclusive|not_needed"
  },
  "key_stuck_points": ["..."],
  "used_results": ["..."],
  "adapted_from": ["relevant statements or proofs whose ideas were migrated"],
  "migration_failures": ["why a proof adaptation or migration failed"],
  "branch_id": "optional"
}
```

Record the plan's updated status (`screening` / `screened` / `solved`) in your
local memory or as a follow-up `plan` finding.

## Tools

- `gm_add` (publish the proof-attempt finding)
- `gm_search` (recall examples, counterexamples, dead-ends, and verified facts)
- `fact_submit` (verify any self-contained partial result before building on it; see `$verify-proof`)
- `search_arxiv_theorems`

## Failure Logging

If a decomposition plan does not solve the problem directly after attempting all of its subgoals, publish a `dead_end` finding (`gm_add`) that summarizes the plan-local stuck points and any important proof-migration failures, so siblings skip them.
