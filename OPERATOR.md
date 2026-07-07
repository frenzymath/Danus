# OPERATOR.md — durable operator profile & standing preferences

> Auto-loaded into every Claude Code session (`CLAUDE.md` imports it with
> `@OPERATOR.md`). It is the main agent's **long-term memory of the operator** —
> the things it learns by asking and must not forget when the session ends. Keep it
> short, factual, current; update in place (no duplicates). **No secrets here**
> (tokens/keys go to `config/*.env`, gitignored). This file is committed.
>
> On a fresh deployment this is the blank template — the `initialize` skill fills it.

## Operator
- **Name / how to address:** _(ask once; fill in)_
- **Language:** _(the language the main agent replies in; code/comments/skills stay English)_
- **Timezone:** _(for scheduling summaries/consults)_

## Standing preferences
- **Notifications:** _(how/where to reach them; what severity warrants a ping)_
- **Spend ceiling (paid consult API):** _(USD; warn before crossing)_
- **Consult transport:** _(`gpt_pro` — paid API, BYO key / `claude_api` — Anthropic API, per-token BYO key / `claude_code` — your Claude subscription / `off` — main agent reasons on its own)_
- **worker roster:** _(default `high:3,xhigh:4` — 3 high + 4 xhigh; asked per project at `danus new`)_

## Per-project pointers
_(One line per live project → where its durable facts live. The project's own
problem lives under `runtime/projects/<project>/PROBLEM.md`, not here.)_

## Notes
_(Anything else durable the operator told you: conventions, do/don't, contacts.)_
