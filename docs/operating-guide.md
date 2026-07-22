# Danus — Operating Guide

How to run a project end to end, from the operator's seat. You do this by **talking
to the main agent** (Claude Code) in natural language; it runs the CLI verbs and
tools for you. Read `concepts.md` first; set up with `getting-started.md`.

> This guide describes the human workflow. Command/tool details are in
> `cli-and-tools.md`.

## The shape of a run

```
initialize ─▶ new project ─▶ strategy loop ⇄ workers prove ─▶ facts accumulate
                                   │                                 │
                            human-summary               you decide the answer
                  (progress report — any time)             → danus finalize
                                                                     ▼
                                                               write-paper
```

You stay in the loop for the judgment calls (is this the answer? push outward?
spend past the ceiling?); everything else the main agent acts on and reports.

## 0. First session — initialize

On a fresh deployment the main agent runs `initialize`: it interviews you (how to
address you + language, git branch off `main`, spend ceiling, consult transport,
codex backend), fills `OPERATOR.md` + `config/danus.env`, brings up the verify
service, and marks `runtime/.danus-initialized`. After that, every session
re-reads your `OPERATOR.md` and the project's `PROBLEM.md`.

## 1. Start a project

Tell the main agent the problem. It will:

1. **Ask the worker roster** — how many `high` + `xhigh` workers (default
   `high:3,xhigh:4` = 3 + 4).
2. **Write `PROBLEM.md`** — your goal, verbatim, under `runtime/projects/<p>/`.
3. **Scaffold** — `danus new <p> --roles high:N,xhigh:M` (creates the workers, the
   empty `global_memory/` + `fact_graph/`).

A **project** is the unit of work: one problem, its own memory and fact graph. You
can run several at once; every operation names a project.

## 2. The strategy loop (steer, don't prove)

The main agent does **not** do the mathematics. It steers, periodically, on genuine
new state:

1. **Elaborate** — distill the shared stores into a high-signal synthesis (verdict,
   closed routes, dangers, the missing bridge lemmas). *(the `elaboration` skill)*
2. **Consult** — send that to a strong model. *(the `consult` skill; `gpt_pro`
   by default, `claude_api`, `claude_code`, or `off`)*
3. **Assign** — record the reply as `master_guidance` and give each worker its
   per-round task (`danus assign`).
4. **Monitor** — watch `danus status` / the dashboard; repeat when there is new
   state.

Cadence is roughly: a strategy consult every ~2h, a human-readable summary every
~1h, while your session is active. **When your session is inactive, only the
workers keep looping** — no auto strategy beats fire (there is no resident cron).
For unattended operation see `operations.md` (the tmux example).

## 3. Workers prove; facts accumulate

`danus start <p>` launches the autonomous worker loops. Each worker reads its
`TASK.md` + `master_guidance`, picks proving skills, works, and submits results via
`fact_submit` — which the **verifier** gates. A submission becomes a **fact** only
on a `correct` verdict; every verdict is traced to global memory either way.

Monitor with:

```bash
danus status <p>                          # per-worker liveness + round + last fact id
bash scripts/services.sh up dashboard <p> # then port-forward :8099 for a visual view
```

You never hand-edit the truth stores and never write facts yourself — the fact
graph is the single verifier-gated source of truth.

## 4. Decide the answer — `danus finalize`

Danus does **not** declare a problem "done" on its own; that is a mathematical
judgment it surfaces to **you**. When the main agent judges every target proved and
the route credible, it **stops the swarm's exploration immediately** (to save
compute — `danus start` resumes it if you disagree), then says so and asks you to
confirm the answer. On your yes:

```bash
danus finalize <project> <fact_id> [<fact_id> …]
```

This records the approved target theorem(s) in `TARGET.md` (what write-paper reads).
`danus finalize <project>` with **no id** prints candidate terminal facts as
suggestions. `finalize` itself only records — the swarm was already stopped above
(on judged completion); `finalize` does not touch the workers.

## 5. Render the output

Two renderers read the verified fact graph:

**Human progress report** — `human-summary` (the `summary_write` tool): a clean,
id-free PDF for you or the mathematician who posed the problem — precise problem
statement, the essential partial results with real proof sketches, the main
obstacle, a neutral timeline, and the remaining lemma. Run it at **any time** to
see where things stand; it is not gated on finalize.

**Publishable paper** — `write-paper`: turns the target's verified facts into a
standalone `amsart` `.tex` with a real bibliography, compiled to PDF. This is the
terminal output: it requires the finalized target (step 4) and refuses to write
without one.

- Entering write-paper does **not** auto-stop the swarm — a **partial**
  result can be written up while the swarm keeps exploring the rest; the main agent
  **asks you** whether to stop exploration first.
- A project can hold **multiple papers** (one theorem each, or several theorems per
  paper) via a `paper_id`; the default paper uses the legacy `<project>/paper/`
  workspace.
- The pipeline drafts, compiles (a hard gate), audits + verifies citations online,
  and re-verifies the whole paper as written through a dedicated paper-math
  verifier before delivery. See the write-paper skill README
  (`.claude/skills/write-paper/README.md`).

## 6. Anything that leaves the machine is your call

Pushing a paper to arXiv / a LaTeX-git repo, revoking a verified fact (it cascades),
and spend past your ceiling are **operator forks**: the main agent confirms with you
before acting, then records the decision.

## Running multiple projects / staying honest

- Run several projects at once; each names its project in every operation.
- The main agent states only what it verified (it saw the fact land, checked the
  exit status) and reports errors/empties plainly — it will not silently retry and
  claim success. If it is unsure, it says so.

---

See `cli-and-tools.md` for the exact verbs and tools, `operations.md` for services
and recovery, and `security-and-trust.md` before you rely on a result.
