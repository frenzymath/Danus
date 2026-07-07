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
  tests/{test_strategy.py, test_claude_code_transport.py, test_claude_api_transport.py}
```

## Transports (`DANUS_CONSULT_TRANSPORT`)

- **`gpt_pro`** (default) — a paid OpenAI-compatible Responses endpoint
  (`DANUS_CONSULT_API_KEY`/`_BASE_URL`/`_MODEL`). Driven `background=True, stream=True`
  (a sync xhigh call would hang the proxy); **400-only** graceful param step-down
  (`full → no-tools → no-effort → bare`). Cost is computed per-call.
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

## The envelope (pinned §6 contract with the consult skill)

One JSON line: `{transport, model, effort, attempt, status, seconds, usage, cost_usd,
tool_calls, reasoning_summary, reply}` (+ `project_total_usd` when `--project` given).
Callers depend on `reply`, `cost_usd`, `transport`, `usage`. The reply is recorded
verbatim as `master_guidance` **by the main agent** (this module writes no stores but
the ledger).

## Tests

`python -m pytest danus/strategy/` (offline; the `openai`/`anthropic`/`claude` clients are stubbed).
