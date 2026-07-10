"""Consult transports — the abstract gateway + the OpenAI-compatible API impl.

A ``Transport`` takes a prompt and returns a uniform JSON envelope (see
``shape_envelope``). ``GptProTransport`` is the default: it drives an
OpenAI-compatible **Responses** API in ``background=True, stream=True`` mode
(required — a synchronous xhigh call hangs the proxy) and steps its params down
only on a 400. ``OffTransport`` short-circuits to a disabled result.

This module is a STATELESS gateway: prompt in, envelope out. It never touches the
truth stores; the only side effect (the spend ledger) lives in ``ledger.py`` and
is driven by the CLI, not here.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

from .config import (
    ClaudeApiConfig, ConsultConfig,
    DEFAULT_CLAUDE_CODE_PRICE_IN, DEFAULT_CLAUDE_CODE_PRICE_OUT,
)

# Tool sets keyed by the --tools switch. "auto" = web_search + code_interpreter;
# "web" = web_search only; "none" = no tools.
_TOOLS_WEB = {"type": "web_search"}
_TOOLS_CODE = {"type": "code_interpreter", "container": {"type": "auto"}}


def tools_for(mode: str) -> List[Dict[str, Any]]:
    if mode == "none":
        return []
    if mode == "web":
        return [_TOOLS_WEB]
    return [_TOOLS_WEB, _TOOLS_CODE]  # auto (default)


def shape_envelope(
    final: Any,
    *,
    transport: str,
    model: str,
    effort: str,
    attempt: str,
    seconds: float,
    status: Optional[str],
    price_in: float,
    price_out: float,
) -> Dict[str, Any]:
    """Shape a raw Responses result into the pinned JSON envelope.

    ``final`` may be ``None`` (a call that produced no completed response); the
    envelope still comes out well-formed with zeroed usage/cost.
    """
    summaries: List[str] = []
    tool_calls: List[str] = []
    output_text = ""
    usage = None
    if final is not None:
        for it in (getattr(final, "output", None) or []):
            ty = getattr(it, "type", None)
            if ty == "reasoning":
                for s in (getattr(it, "summary", None) or []):
                    summaries.append(getattr(s, "text", "") or "")
            elif ty in ("web_search_call", "code_interpreter_call"):
                tool_calls.append(ty)
        output_text = getattr(final, "output_text", "") or ""
        usage = getattr(final, "usage", None)
    u = usage.model_dump() if (usage is not None and hasattr(usage, "model_dump")) else {}
    in_tok = int(u.get("input_tokens", 0) or 0)
    out_tok = int(u.get("output_tokens", 0) or 0)
    cost = in_tok / 1e6 * price_in + out_tok / 1e6 * price_out
    reasoning_tok = (u.get("output_tokens_details") or {}).get("reasoning_tokens")
    return {
        "transport": transport,
        "model": model,
        "effort": effort,
        "attempt": attempt,
        "status": status,
        "seconds": round(seconds, 1),
        "usage": {"input": in_tok, "output": out_tok, "reasoning": reasoning_tok},
        "cost_usd": round(cost, 4),
        "tool_calls": tool_calls,
        "reasoning_summary": "\n\n---\n\n".join(summaries),
        "reply": output_text,
    }


class Transport:
    """Abstract consult transport."""

    name = "abstract"

    def consult(
        self,
        prompt: str,
        *,
        effort: str,
        tools: str,
        max_output_tokens: int,
        on_progress: Optional[Callable[[float, Optional[str], int], None]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class OffTransport(Transport):
    """Disabled transport — a no-op that returns a well-formed, $0 envelope so
    the caller can proceed without a key / spend."""

    name = "off"

    def consult(self, prompt, *, effort, tools, max_output_tokens, on_progress=None):
        return {
            "transport": "off",
            "model": None,
            "effort": effort,
            "attempt": "disabled",
            "status": "disabled",
            "seconds": 0.0,
            "usage": {"input": 0, "output": 0, "reasoning": None},
            "cost_usd": 0.0,
            "tool_calls": [],
            "reasoning_summary": "",
            "reply": "",
        }


class GptProTransport(Transport):
    """OpenAI-compatible Responses transport (the default).

    ``client_factory`` lets tests inject a stub client without a real OpenAI
    package or network; production builds it from the config.
    """

    name = "gpt_pro"

    def __init__(self, config: ConsultConfig, client_factory: Optional[Callable[[], Any]] = None):
        self.config = config
        self._client_factory = client_factory or self._default_client

    def _default_client(self):
        from openai import OpenAI  # imported lazily so `off` needs no openai

        return OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    @staticmethod
    def _run_stream(client, create_kwargs, on_progress=None):
        """Drive ONE background+stream Responses call to its end. Returns
        (final_response_or_None, n_events, status, seconds). Streamed events keep
        the connection alive so a long initial reasoning gap never hangs."""
        t0 = time.time()
        n = 0
        status: Optional[str] = None
        final = None
        last_hb = t0
        stream = client.responses.create(background=True, stream=True, **create_kwargs)
        for ev in stream:
            n += 1
            et = getattr(ev, "type", "?")
            resp = getattr(ev, "response", None)
            if resp is not None:
                st = getattr(resp, "status", None)
                if st:
                    status = st
            if et == "response.completed":
                final, status = ev.response, "completed"
            elif et in ("response.failed", "response.incomplete"):
                final = ev.response
                status = getattr(ev.response, "status", et)
            now = time.time()
            if on_progress and (now - last_hb >= 30 or et == "response.completed"):
                on_progress(now - t0, status, n)
                last_hb = now
        return final, n, status, time.time() - t0

    def consult(self, prompt, *, effort, tools, max_output_tokens, on_progress=None):
        """Background+stream consult; step params down ONLY on a 400 (param
        rejected), never on a timeout/connection error (those must surface)."""
        from openai import BadRequestError

        client = self._client_factory()
        tool_list = tools_for(tools)
        # richest first; a 400 (a tool/effort the model rejects) steps down.
        attempts = [
            ("full", dict(reasoning={"effort": effort, "summary": "detailed"}, tools=tool_list)),
            ("no-tools", dict(reasoning={"effort": effort, "summary": "detailed"})),
            ("no-effort", dict(reasoning={"summary": "detailed"}, tools=tool_list)),
            ("bare", dict()),
        ]
        last: Optional[Exception] = None
        for name, extra in attempts:
            try:
                final, n, status, dt = self._run_stream(
                    client,
                    dict(model=self.config.model, input=prompt,
                         max_output_tokens=max_output_tokens, **extra),
                    on_progress=on_progress,
                )
                return shape_envelope(
                    final,
                    transport="gpt_pro",
                    model=self.config.model,
                    effort=effort,
                    attempt=name,
                    seconds=dt,
                    status=status,
                    price_in=self.config.price_in,
                    price_out=self.config.price_out,
                )
            except BadRequestError as e:
                last = e
                continue
        assert last is not None
        raise last


# ---- claude_code transport (your subscription, via the Claude Code CLI) -------

# Prepended via --append-system-prompt so the subscription model behaves as a
# non-interactive strategy advisor and answers directly. Mirrors the gpt_pro path's
# role: the reply is recorded verbatim as master_guidance.
ADVISOR_SYSTEM = (
    "You are a senior research-mathematics strategy advisor, consulted by an "
    "automated proof-search orchestrator. You will receive the current distilled "
    "state (an 'elaboration') of a mathematics project whose worker swarm proves "
    "results. Respond with concrete strategy: the most promising decomposition(s) "
    "of the problem and the single most actionable next lemma/step for the workers. "
    "Be rigorous and specific — name precise techniques, lemmas, references. Do NOT "
    "ask questions (this is non-interactive; resolve ambiguity yourself). Output "
    "only the strategic guidance, with no preamble or meta-commentary; this text is "
    "recorded verbatim as the swarm's master_guidance."
)


def claude_tools_for(mode: str) -> List[str]:
    """The claude ``--tools`` allowlist. Least-privilege and FIXED to web-lookup
    tools only (WebSearch/WebFetch), for EVERY ``mode`` — never Bash / file-editing
    / exec tools, since the advisor only reasons and runs under
    ``--permission-mode bypassPermissions``.

    We deliberately never emit an empty allowlist: ``claude --tools ""`` does NOT
    disable tools — a lone empty token makes the CLI fall back to the FULL default
    set (Bash/Write/Edit/Task/...). So even ``mode == "none"`` maps to web-only.
    """
    return ["WebSearch", "WebFetch"]


# Anthropic auth/routing overrides scrubbed from the child env so `claude` uses the
# interactive subscription (OAuth login), NOT a per-token API key/token or a custom
# proxy endpoint. Leaving any of these set would silently route the consult through
# a per-token API / proxy instead of the subscription auth this transport expects.
_SCRUB_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)

# claude --effort accepts these; the consult CLI also offers "minimal", which claude
# ignores (warns + uses default) — normalize it to the nearest supported level.
_CLAUDE_CODE_EFFORTS = ("low", "medium", "high", "xhigh", "max")


class ClaudeCodeTransport(Transport):
    """Consult via the Claude Code CLI through ``claude -p`` — routed through the CLI's
    subscription auth (not a per-token API key/proxy). The dollar cost is metered
    the same way as gpt_pro: ``input/output tokens × the per-1M rate`` from
    ``ClaudeCodeConfig`` (``DANUS_CONSULT_CLAUDE_CODE_PRICE_IN`` / ``_OUT``, estimate
    defaults — set them to your real model/plan rate). It is recorded to the spend
    ledger like any other consult; it is NOT free.

    Isolation (all deliberate):
      * runs in a throwaway cwd so the nested ``claude`` does NOT load the
        caller's CLAUDE.md / .mcp.json and try to *orchestrate* — it only reasons;
      * loads NO settings and NO MCP servers (``--setting-sources "" +
        --strict-mcp-config``), so user-level CLAUDE.md / memory / user-scope MCP
        servers stay out of the consult context — the advisor sees the elaboration
        prompt and the public web, nothing else;
      * the prompt travels on **stdin**, never argv (argv is world-readable via
        ``/proc`` on a shared host; the elaboration is unpublished research);
      * scrubs the Anthropic auth/routing overrides (``_SCRUB_ENV``) from the child
        env so it uses the subscription auth, not a per-token API key / a proxy;
      * least-privilege tools (web lookups only, never Bash) via ``--tools``.

    ``runner`` is injectable so tests can stub the subprocess with no real
    ``claude`` binary and no network.
    """

    name = "claude_code"

    def __init__(self, model: str, *, claude_bin: str = "claude",
                 max_wall: float = 1800.0,
                 price_in: float = DEFAULT_CLAUDE_CODE_PRICE_IN,
                 price_out: float = DEFAULT_CLAUDE_CODE_PRICE_OUT,
                 runner: Optional[Callable[..., Any]] = None):
        self.model = model
        self.claude_bin = claude_bin
        self.max_wall = max_wall
        self.price_in = price_in
        self.price_out = price_out
        self._runner = runner or self._default_runner

    @staticmethod
    def _default_runner(cmd, *, input, cwd, env, timeout):
        return subprocess.run(cmd, input=input, capture_output=True, text=True,
                              cwd=cwd, env=env, timeout=timeout)

    @staticmethod
    def _pick_main_model(model_usage: Dict[str, Any], requested: str):
        """Return (model_that_did_the_work, fell_back?). Claude Code uses a small
        helper model (haiku) for internal steps; the main responder is the
        non-haiku key with the most output tokens. A requested model absent from
        the keys means a safety/availability fallback ran (e.g. Fable -> Opus)."""
        keys = list(model_usage.keys())
        if not keys:
            return requested, False
        non_helper = {k: v for k, v in model_usage.items()
                      if "haiku" not in k.lower()} or model_usage
        main = max(non_helper.items(),
                   key=lambda kv: (kv[1] or {}).get("outputTokens", 0))[0]
        fell_back = not any(k == requested or k.startswith(requested) for k in keys)
        return main, fell_back

    def _envelope(self, *, reply, effort, seconds, status, used_model, requested,
                  fell_back, usage, web_searches):
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        # Metered like gpt_pro: tokens × the per-1M rate from ClaudeCodeConfig. A failed
        # call (timeout/error) has no usage ⇒ zero tokens ⇒ 0.0, honestly.
        cost = round(in_tok / 1e6 * self.price_in + out_tok / 1e6 * self.price_out, 4)
        return {
            "transport": "claude_code",
            "model": (f"{used_model} (fell back from {requested})"
                      if fell_back else used_model),
            "effort": effort,
            "attempt": "claude-code",
            "status": status,
            "seconds": round(seconds, 1),
            "usage": {"input": in_tok,
                      "output": out_tok,
                      "reasoning": None},
            "cost_usd": cost,  # tokens × per-1M rate (DANUS_CONSULT_CLAUDE_CODE_PRICE_IN/_OUT)
            "tool_calls": ["web_search"] * int(web_searches or 0),
            "reasoning_summary": "",
            "reply": reply,
        }

    def consult(self, prompt, *, effort, tools, max_output_tokens, on_progress=None):
        effort = effort if effort in _CLAUDE_CODE_EFFORTS else "low"  # "minimal" -> "low"
        cmd = [
            self.claude_bin, "-p",
            "--model", self.model,
            "--effort", effort,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
            "--append-system-prompt", ADVISOR_SYSTEM,
            # Load NO settings (no user/project CLAUDE.md, no memory) and NO MCP
            # servers: the advisor sees the elaboration and the web, nothing else.
            # Complements the throwaway cwd below. Requires a recent claude CLI.
            "--setting-sources", "",
            "--strict-mcp-config",
            "--tools", *claude_tools_for(tools),
        ]
        # Force the subscription: drop every Anthropic auth/routing override so the
        # child cannot silently bill per-token / hit a proxy (see _SCRUB_ENV).
        env = {k: v for k, v in os.environ.items() if k not in _SCRUB_ENV}
        t0 = time.time()
        # Neutral cwd: don't inherit the caller's CLAUDE.md / MCP wiring. The
        # prompt goes on STDIN, never argv — argv is world-readable in /proc.
        with tempfile.TemporaryDirectory(prefix="danus-consult-") as cwd:
            try:
                proc = self._runner(cmd, input=prompt, cwd=cwd, env=env,
                                    timeout=self.max_wall)
            except subprocess.TimeoutExpired:
                return self._envelope(reply="", effort=effort, seconds=self.max_wall,
                                      status="timeout", used_model=self.model,
                                      requested=self.model, fell_back=False,
                                      usage={}, web_searches=0)
        dt = time.time() - t0

        # The JSON result object is the last JSON line on stdout; tolerate noise.
        parsed = None
        for ln in reversed([l for l in (proc.stdout or "").splitlines() if l.strip()]):
            try:
                parsed = json.loads(ln)
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            return self._envelope(reply="", effort=effort, seconds=dt, status="error",
                                  used_model=self.model, requested=self.model,
                                  fell_back=False, usage={}, web_searches=0)

        reply = (parsed.get("result") or "").strip()
        is_error = bool(parsed.get("is_error")) or parsed.get("subtype") not in (None, "success")
        used, fell_back = self._pick_main_model(parsed.get("modelUsage") or {}, self.model)
        usage = parsed.get("usage") or {}
        web = (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
        seconds = (parsed.get("duration_ms") or 0) / 1000.0 or dt
        status = "completed" if (reply and not is_error) else "error"
        return self._envelope(reply=reply, effort=effort, seconds=seconds, status=status,
                              used_model=used, requested=self.model, fell_back=fell_back,
                              usage=usage, web_searches=web)


# ---- claude_api transport (native Anthropic API, per-token, BYO key) -----------

# Server-side refusal-fallback beta (claude-fable-5's safety classifiers can
# decline a benign-adjacent request; with this, the API re-serves it on the
# fallback model inside the same call). The header value is pinned by Anthropic —
# do not "update" the date.
_CLAUDE_API_FALLBACK_BETA = "server-side-fallback-2026-06-01"

# `output_config.effort` accepts these; the consult CLI also offers "minimal",
# which we normalize to the nearest supported level.
_CLAUDE_API_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# Server tools hit an internal iteration cap and return stop_reason="pause_turn";
# the documented handling is to re-send and let the server resume. Bound it.
_CLAUDE_API_MAX_CONTINUATIONS = 4


def claude_api_tools_for(mode: str) -> List[Dict[str, Any]]:
    """The Anthropic server-tool list. ``none`` disables tools; every other mode
    maps to server-side web search (grounding). Code execution is deliberately
    NOT offered: the consult is a reasoning step, and correctness in Danus comes
    from the verifier, never from a number a consult computed."""
    if mode == "none":
        return []
    return [{"type": "web_search_20260209", "name": "web_search"}]


class ClaudeApiTransport(Transport):
    """Consult via the native Anthropic API (the ``anthropic`` SDK) — per-token
    billing to YOUR key (``DANUS_CONSULT_CLAUDE_API_KEY``, else
    ``ANTHROPIC_API_KEY``), unlike the ``claude_code`` transport's subscription auth.
    The cost in the envelope is computed from the response's REAL token usage ×
    the per-1M rates (``DANUS_CONSULT_CLAUDE_API_PRICE_IN`` / ``_OUT``; defaults
    match the default model's list price).

    Request shape (kept compatible across the current model family by stepping
    down on a 400, mirroring ``GptProTransport``):
      * ``thinking={"type": "adaptive", "display": "summarized"}`` — adaptive
        reasoning with a readable summary (recorded as ``reasoning_summary``);
      * ``output_config={"effort": ...}`` — the depth knob (default xhigh);
      * server-side web search for grounding (see ``claude_api_tools_for``);
      * streaming always (long xhigh consults exceed non-streaming HTTP limits).

    Refusals: the default model (claude-fable-5) runs safety classifiers that can
    false-positive on benign-adjacent work, so by default the request carries the
    server-side refusal-fallback parameter (beta) naming
    ``ClaudeApiConfig.fallback_model`` — a decline is transparently re-served by
    that model in the same call. Set ``DANUS_CONSULT_CLAUDE_API_FALLBACK=off`` to
    opt out. If the installed SDK predates the typed ``fallbacks`` param we fall
    back to a plain request (TypeError guard) rather than failing the consult.

    ``client_factory`` lets tests inject a stub client without the ``anthropic``
    package or network; production builds it from the config.
    """

    name = "claude_api"

    def __init__(self, config: ClaudeApiConfig,
                 client_factory: Optional[Callable[[], Any]] = None):
        self.config = config
        self._client_factory = client_factory or self._default_client

    def _default_client(self):
        from anthropic import Anthropic  # lazy so other transports need no anthropic

        return Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    # -- streaming ---------------------------------------------------------

    def _open_stream(self, client, kwargs: Dict[str, Any]):
        """Open ONE message stream, attaching the refusal-fallback parameter when
        configured (beta namespace). Returns the stream context manager."""
        fb = self.config.fallback_model
        if fb and fb != kwargs.get("model"):
            try:
                return client.beta.messages.stream(
                    betas=[_CLAUDE_API_FALLBACK_BETA],
                    fallbacks=[{"model": fb}],
                    **kwargs,
                )
            except TypeError:
                # SDK too old for the typed fallbacks param — degrade to a plain
                # request (a refusal then simply fails the consult; honest).
                pass
        return client.messages.stream(**kwargs)

    def _run_stream(self, client, kwargs, on_progress=None):
        """Drive one stream to its end. Returns (final_message, seconds).
        Streaming keeps the connection alive through long thinking gaps and lets
        us heartbeat like the gpt_pro path."""
        t0 = time.time()
        n = 0
        last_hb = t0
        with self._open_stream(client, kwargs) as stream:
            for _ev in stream:
                n += 1
                now = time.time()
                if on_progress and now - last_hb >= 30:
                    on_progress(now - t0, "streaming", n)
                    last_hb = now
            final = stream.get_final_message()
        return final, time.time() - t0

    # -- envelope ----------------------------------------------------------

    @staticmethod
    def _collect(final: Any):
        """Pull (reply, reasoning_summary, tool_calls, used_model) out of ONE
        final message's content blocks."""
        texts: List[str] = []
        thinking: List[str] = []
        tool_calls: List[str] = []
        for block in (getattr(final, "content", None) or []):
            ty = getattr(block, "type", None)
            if ty == "text":
                texts.append(getattr(block, "text", "") or "")
            elif ty == "thinking":
                t = getattr(block, "thinking", "") or ""
                if t.strip():
                    thinking.append(t)
            elif ty == "server_tool_use":
                tool_calls.append(getattr(block, "name", "server_tool_use"))
        return texts, thinking, tool_calls

    @staticmethod
    def _usage_tokens(final: Any):
        """(input_tokens incl. cache reads/writes, output_tokens) of one message."""
        u = getattr(final, "usage", None)
        if u is None:
            return 0, 0
        in_tok = int(getattr(u, "input_tokens", 0) or 0)
        in_tok += int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        in_tok += int(getattr(u, "cache_read_input_tokens", 0) or 0)
        return in_tok, int(getattr(u, "output_tokens", 0) or 0)

    def consult(self, prompt, *, effort, tools, max_output_tokens, on_progress=None):
        """Streamed consult; step params down ONLY on a 400 (a param/tool the
        model rejects), never on a timeout/connection error (those must surface).
        ``stop_reason == "pause_turn"`` (server-tool iteration cap) is continued
        transparently, up to ``_CLAUDE_API_MAX_CONTINUATIONS`` times."""
        from anthropic import BadRequestError  # lazy, mirrors the openai import

        client = self._client_factory()
        eff = effort if effort in _CLAUDE_API_EFFORTS else "low"  # "minimal" -> "low"
        tool_list = claude_api_tools_for(tools)
        thinking = {"type": "adaptive", "display": "summarized"}
        # richest first; a 400 (a param/tool the model rejects) steps down.
        attempts = [
            ("full", dict(thinking=thinking, output_config={"effort": eff}, tools=tool_list)),
            ("no-tools", dict(thinking=thinking, output_config={"effort": eff})),
            ("no-thinking", dict(output_config={"effort": eff}, tools=tool_list)),
            ("bare", dict()),
        ]
        max_tokens = max(1, min(int(max_output_tokens), 128000))
        last: Optional[Exception] = None
        for name, extra in attempts:
            if not extra.get("tools"):
                extra = {k: v for k, v in extra.items() if k != "tools"}
            messages = [{"role": "user", "content": prompt}]
            base = dict(model=self.config.model, max_tokens=max_tokens,
                        system=ADVISOR_SYSTEM, **extra)
            try:
                texts: List[str] = []
                thinks: List[str] = []
                calls: List[str] = []
                in_tok = out_tok = 0
                seconds = 0.0
                final = None
                for _round in range(1 + _CLAUDE_API_MAX_CONTINUATIONS):
                    final, dt = self._run_stream(
                        client, dict(base, messages=list(messages)),
                        on_progress=on_progress,
                    )
                    seconds += dt
                    t, th, c = self._collect(final)
                    texts += t
                    thinks += th
                    calls += c
                    i, o = self._usage_tokens(final)
                    in_tok += i
                    out_tok += o
                    if getattr(final, "stop_reason", None) != "pause_turn":
                        break
                    # server-tool loop paused: re-send with the assistant turn
                    # appended; the server resumes where it left off.
                    messages.append({"role": "assistant",
                                     "content": getattr(final, "content", [])})
                stop = getattr(final, "stop_reason", None)
                status = {"end_turn": "completed", "refusal": "refusal",
                          "max_tokens": "incomplete",
                          "pause_turn": "incomplete"}.get(stop, stop or "completed")
                requested = self.config.model
                used = getattr(final, "model", None) or requested
                fell_back = not (used == requested or str(used).startswith(requested))
                cost = round(in_tok / 1e6 * self.config.price_in
                             + out_tok / 1e6 * self.config.price_out, 4)
                return {
                    "transport": "claude_api",
                    "model": (f"{used} (fell back from {requested})"
                              if fell_back else used),
                    "effort": eff,
                    "attempt": name,
                    "status": status,
                    "seconds": round(seconds, 1),
                    "usage": {"input": in_tok, "output": out_tok, "reasoning": None},
                    "cost_usd": cost,  # REAL usage × per-1M rate (DANUS_CONSULT_CLAUDE_API_PRICE_IN/_OUT)
                    "tool_calls": calls,
                    "reasoning_summary": "\n\n---\n\n".join(thinks),
                    "reply": "".join(texts).strip(),
                }
            except BadRequestError as e:
                last = e
                continue
        assert last is not None
        raise last
