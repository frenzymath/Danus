---
name: initialize
description: First-run setup interview for a Danus deployment. Run it on the FIRST session, whenever runtime/.danus-initialized is absent or OPERATOR.md is still the blank template, or when the operator asks to set up / initialize / onboard / re-configure. It greets the operator, explains Danus, uses the AskUserQuestion popup to collect the two critical choices (codex backend, GPT-5.5-pro consult transport) plus a few free-text fields (how to address them, language, git branch, spend ceiling), then provisions everything (branch, config/danus.env, OPERATOR.md, codex login, verify service) and marks runtime/.danus-initialized. The system cannot run without these answers, so do not skip it.
---

# initialize — first-run setup interview

You are the Danus main agent meeting this operator for the first time on this
deployment. Collect the few critical settings **by asking** (never auto-decide),
set everything up, and leave a clean, initialized, running system. Use the popup so
the choices are one click. Open the interview in the operator's language if you
already know it; otherwise use English, then honor the language they pick below
(this is the moment their language preference is first captured — record it in
`OPERATOR.md` and follow it thereafter).

## 0. Greet + orient (brief)

Tell the operator, in 2–3 sentences: Danus is an automated mathematics system —
codex **workers** prove, a **verifier** is the sole gate on correctness, and you
(Claude Code) **orchestrate**; you'll ask a few setup questions, then you're ready
to take a problem. Say the answers are saved permanently (`OPERATOR.md`), so this
is a one-time setup.

## 1. Read current state (so you don't ask about what's already done)

```bash
bash scripts/doctor.sh
git branch --show-current
```
Note: codex reachable? on `main` (needs a working branch)? `config/danus.env`
present? `OPERATOR.md` filled or still the template?

## 2. Ask the choices — use the **AskUserQuestion** popup

Make ONE AskUserQuestion call with these multiple-choice questions (the operator
clicks; put the recommended option first):

- **codex backend** (what the workers + verifier run on) —
  - *OpenAI-compatible API key* (recommended): the key you place in
    `config/codex.env` — works immediately, no login.
  - *My own ChatGPT subscription*: device-code login.
- **strategy consults transport** (the periodic high-intelligence steer) —
  - *Paid OpenAI-compatible API key* (`gpt_pro`, recommended): a Responses endpoint.
  - *Anthropic API key* (`claude_api`): the native Anthropic API, per-token.
  - *Claude subscription* (`claude_code`): the Claude Code CLI's login; no separate key.
  - *Off*: you reason on your own; no external consults.

Then ask, as plain text questions (not the popup):
- How to address them (name), and their **language** (default English) — this sets
  the language you use with them from now on (`OPERATOR.md` records it).
- The **git working branch** name (default `deploy/<operator-or-host>`).
- If they chose the **paid-API** consult path: a **spend ceiling** (USD) to warn at.

## 3. Provision — act on the answers, persisting each before moving on

- **Branch:** if on `main`, `git checkout -b <branch>` (never work on `main`).
- **Config:** `cp -n config/danus.env.example config/danus.env`; set `CODEX_BACKEND`
  and `DANUS_CONSULT_TRANSPORT` (`gpt_pro` / `claude_api` / `claude_code` / `off`) to their choices. If the backend is
  the OpenAI-compatible key, `cp -n config/codex.env.example config/codex.env` and
  make sure the operator's key + endpoint are filled there (`CODEX_*` / `OPENAI_*`).
  Never put secrets anywhere but `config/*.env`.
- **OPERATOR.md:** fill name / language / consult transport / spend ceiling /
  default worker roster, in place (no duplicates).
- **codex:** backend=api → `bash scripts/check-codex.sh` (confirm reachable);
  backend=chatgpt → **you** run `bash scripts/setup-codex.sh login` and give the
  operator the printed URL + device code (they only open it and authorize).
- **consult transport:** consult=gpt_pro or claude_api → verify the key actually resolves before
  claiming it works: run one short `consult` test on the chosen transport (a single
  bounded prompt, e.g. "Reply with one sentence confirming you can answer."; for
  `claude_api` add `--effort low --tools none` to keep it cheap) and read the
  envelope; `status:"completed"` with a non-empty `reply` ⇒ the api path works.
  consult=off → nothing to wire.
- **Services (must persist beyond your session — `services.sh` uses setsid):**
  `bash scripts/services.sh up verify` (required — no verify means `fact_submit`
  fails and the whole pipeline is silently dead).
- **Verify the stack:** `bash scripts/doctor.sh`; report green/red plainly.
- **Mark done:** `mkdir -p runtime && date -u +%FT%TZ > runtime/.danus-initialized`.
- **Commit** (git discipline): commit `OPERATOR.md` (and the new branch) locally — do
  **not** push (push is an explicit operator action, never automatic; see `CLAUDE.md`).
  Never commit `config/*.env` or `runtime/`.

## 4. Hand off

Summarize the chosen backend / transport, confirm the system is up, then ask
for the **math problem** (or return to the operator's original request). When they
give it, write `runtime/projects/<p>/PROBLEM.md` and begin the strategic loop.

Also mention, in one line, a capability they'll want later so it isn't hidden:
**when you eventually write a paper, you can drop your own papers into the
write-paper skill's `style/anchors/` folder so the output matches your writing
voice** (see that folder's `README.md`; a complete paper is produced either way).

**Rules:**
- **Ask, don't assume** — the choices are the operator's call. "Use the defaults"
  is fine, but record it explicitly. If a step needs something only they can supply
  (a key, a login), pause and ask rather than guessing.
- **Verify, never claim unchecked.** Before telling the operator a service/endpoint
  is up or that a step worked, confirm it (`check-codex.sh` exits non-zero on ping
  failure; the api consult test above; `doctor.sh` for the rest). A premature
  "it's up" that turns out to be a failure is exactly what to avoid.
- **Never work on `main`** — branch first if on `main`.
- **Secrets only in `config/*.env`** — never commit `config/*.env` or `runtime/`;
  only `OPERATOR.md` (and the branch) are committed.
- **Invoke scripts from the repo root** (or by absolute path). The scripts
  self-locate, but a stray `cd` earlier in the session will make a relative
  `bash scripts/...` call fail — `cd` to the project dir first if unsure.
- **Persist each answer before moving on**, and only write `runtime/.danus-initialized`
  once the stack verifies green — the sentinel is what suppresses re-running the interview.
