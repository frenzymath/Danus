---
name: propose-subgoal-decomposition-plans
description: Propose multiple subgoal decomposition plans for the current theorem using the information already gathered. Use when enough information has been collected from examples, counterexamples, search results, and previous failures to break the problem into several materially different plans.
---

# Propose Subgoal Decomposition Plans

Use this skill when the agent has enough context to propose several viable decomposition plans.

## Input Contract

Read:

- the current target theorem or branch goal
- relevant `immediate_conclusions`, `toy_examples`, and `counterexamples`
- relevant `failed_paths` and `branch_states`
- recent search results and useful references from `events`

## Procedure

1. Gather the current information that materially constrains the problem: useful examples, failed claims, known obstructions, and relevant search results.
2. Propose materially different decomposition plans.
3. For each plan, state:
   - the main idea of the plan
   - the ordered subgoals
   - why this plan is plausible given the current information
   - which earlier failures or counterexamples it tries to avoid
4. Hand each plan to `$direct-proving` for a quick screening pass.

## Output Contract

Publish one plan per decomposition to global memory with `gm_add` (kind `plan`, a
judgment — `verifiable=false`): `claim` = the plan's goal + summary, `evidence` =
its motivation, plus these fields:

```json
{
  "plan_id": "...",
  "record_type": "decomposition_plan",
  "goal": "...",
  "plan_summary": "...",
  "subgoals": ["..."],
  "motivation": ["..."],
  "uses_information_from": {
    "examples": ["..."],
    "counterexamples": ["..."],
    "key_failures": ["..."],
    "search_results": ["..."]
  },
  "status": "proposed|screening|screened|selected|failed|solved",
  "branch_id": "optional"
}
```

Also note the new plan set in your local memory (`events`).

## Tools

- `gm_add` (publish the plan findings)
- `gm_search` (recall the examples/counterexamples/dead-ends the plans build on)
- `search_arxiv_theorems`

## Failure Logging

If the agent cannot yet propose meaningful decomposition plans, append an `events` record with:

- `event_type="decomposition_plans_not_ready"`
- the missing information
- the blockers that prevent proposing plans
