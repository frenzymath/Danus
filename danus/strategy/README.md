# danus/strategy — the consult gateway (the system's brain)

The main agent's high-intelligence step: send the current **elaboration** to a strong
reasoning model, take its reply as the next `master_guidance`. Transport-abstracted
and **stateless** (writes only the spend ledger). Run via `bin/consult`
(`python -m danus.strategy`).

```
danus/strategy/
  cli.py         parse args, drive a transport, print the JSON envelope
  config.py      ConsultConfig + resolve_transport (env, read at call time)
  transport.py   the transports + the consult call, cost math, param step-down
  ledger.py      append-only spend ledger (<project>/spend/consult.jsonl) + running total
  __main__.py    `python -m danus.strategy` (what bin/consult execs)
  tests/{test_strategy.py, test_claude_code_transport.py, test_claude_api_transport.py, test_dsh_transport.py}
```

## Transports (`DANUS_CONSULT_TRANSPORT`)

- **`gpt_pro`** (default) — a paid OpenAI-compatible Responses endpoint
  (`DANUS_CONSULT_API_KEY`/`_BASE_URL`/`_MODEL`). Driven `stream=True` with the
  canonical message-list `input` shape (a sync xhigh call would hang the proxy).
  `background` / `store` are config knobs (`DANUS_CONSULT_BACKGROUND`, default on;
  `DANUS_CONSULT_STORE`, default off — consult prompts are not server-stored). A
  stricter gateway that rejects one of them 400s, and the endpoint's own error
  surfaces naming the parameter; the caller then re-runs with `--background off` /
  `--store on` / `--max-output-tokens 0` (per-call flags that override the env, like
  `--model`; `0` omits the token cap entirely), and pins it in config only if the
  deployment always needs it. The transport does not parse the
  message to retry — the caller is an agent that can read the error, and guessing
  would silently re-negotiate on every call. 400s on effort/tools use the graceful
  step-down (`full → no-tools → no-effort → bare`); `max` instead preserves its
  effort (`full → no-tools → no-summary → effort-only`). Cost is computed per-call.
  Streamed output-text deltas are retained as the reply when a compatible gateway
  returns a sparse final `response.completed` object.
- **`claude_api`** — the native Anthropic API (per-token, BYO key; the envelope cost
  is the response's REAL usage × the per-1M rates). Streamed; adaptive thinking +
  `output_config.effort`; server-side web search; refusal-fallback param attached
  by default (`DANUS_CONSULT_CLAUDE_API_FALLBACK`, `off` disables); **400-only**
  step-down (`full → no-tools → no-thinking → bare`); `pause_turn` continued.
  Knobs: `DANUS_CONSULT_CLAUDE_API_KEY`/`_BASE_URL`/`_MODEL`/`_FALLBACK`/`_PRICE_*`.
- **`claude_code`** — your Claude subscription via the Claude Code CLI (no separate API key;
  draws on your plan's quota — beyond-plan or premium-model usage can bill extra, and
  the consult is metered into the ledger at the `DANUS_CONSULT_CLAUDE_CODE_PRICE_*` estimate
  rates. Do NOT set `ANTHROPIC_API_KEY`: the transport scrubs it so the consult cannot
  silently switch to per-token API billing — that is what `claude_api` is for).
  Knobs: `DANUS_CONSULT_CLAUDE_CODE_MODEL`/`_BIN`/`DANUS_CONSULT_CLAUDE_CODE_MAX_WALL`.
- **`off`** — no consult; the main agent reasons on its own (the CLI returns a valid
  `$0` envelope with a non-zero exit as an expected signal).

## Reasoning effort

`--effort` accepts `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`.
All transports support through `max`. On `gpt_pro`, a `max` request may simplify
unsupported summary/tool parameters, but it never falls back to a request with no
reasoning effort; an endpoint that rejects `max` therefore fails visibly instead
of producing a misleading strongest-level ledger entry. Lower levels retain the
documented compatibility step-down, exposed through the envelope's `attempt` field.

## The envelope (pinned §6 contract with the consult skill)

One JSON line: `{transport, model, effort, attempt, status, seconds, usage, cost_usd,
tool_calls, reasoning_summary, reply}` (+ `project_total_usd` when `--project` given).
Callers depend on `reply`, `cost_usd`, `transport`, `usage`. The reply is recorded
verbatim as `master_guidance` **by the main agent** (this module writes no stores but
the ledger).

## Tests

`python -m pytest danus/strategy/` (offline; the `openai`/`anthropic`/`claude` clients are stubbed).
