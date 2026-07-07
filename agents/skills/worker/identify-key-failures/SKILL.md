---
name: identify-key-failures
description: Synthesize the common stuck points across failed decomposition plans. Use when the current batch of decomposition plans has failed — whether they failed already at direct proving or only after further attempts.
---

# Identify Key Failures

Use this skill to turn many failed attempts into reusable guidance for the next planning round.

## Input Contract

Read:

- the failed decomposition plans
- direct-proving stuck points
- existing `failed_paths`
- relevant `counterexamples` and `toy_examples`

## Procedure

1. Gather the reports from all failed plans. If only direct proving has run so far, work directly from the direct-proving failures.
2. List the key stuck points for each plan.
3. Identify common points across those failures:
   - recurring obstructions or counterexamples
   - decomposition patterns that keep breaking
   - search gaps or missing background facts
4. Summarize what the failures suggest for the next generation of decomposition plans.
5. When all current decomposition plans have failed and no pattern is leading anywhere, publish the synthesized `dead_end` (below): the main agent reads it and consults for a fresh missing-mechanism or alternative direction (delivered as `master_guidance`), which the next planning round picks up.
6. Save the synthesized failure knowledge to `failed_paths` so later planning skills can use it.
7. After recording the failure synthesis, return control to `$propose-subgoal-decomposition-plans`.

## Output Contract

Publish the failure synthesis to global memory with `gm_add` (kind `dead_end`):
`claim` = the common stuck points, `evidence` = the per-plan failures, so siblings
skip these paths. Carry these fields:

```json
{
  "record_type": "key_failures_summary",
  "failed_plan_ids": ["..."],
  "plan_failures": [
    {
      "plan_id": "...",
      "stuck_points": ["..."]
    }
  ],
  "common_failures": ["..."],
  "implications_for_next_plans": ["..."]
}
```

Also note in your local memory (`events`) that a new planning round is needed.

## Tools

- `gm_add` (publish the dead_end synthesis)
- `gm_search` (gather the failed plans and stuck points across the swarm)

## Failure Logging

If the reports are too weak to identify meaningful common failures, note in local memory (`events`) `event_type="key_failures_inconclusive"` and state what information is still missing.
