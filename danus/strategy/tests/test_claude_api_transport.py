"""Offline tests for the native Anthropic-API consult transport.

The SDK is stubbed two ways, mirroring the sibling suites: a fake ``anthropic``
module installed in ``sys.modules`` (the transport imports it lazily), and an
injectable ``client_factory`` returning a stub client whose ``messages.stream``
/ ``beta.messages.stream`` yield canned events + a canned final message. No
``anthropic`` package and no network are needed.

We assert: the pinned envelope (reply / reasoning summary / tool calls / REAL
usage × per-1M cost), the refusal-fallback wiring (beta header + fallbacks param
by default, TypeError degradation on an old SDK, opt-out), the 400 step-down
ladder, pause_turn continuation, refusal status, and the CLI branch (key gate,
ledger, exit codes).

Runs standalone (``python -m danus.strategy.tests.test_claude_api_transport``)
and under pytest. Kept separate from test_strategy.py.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path

from danus.strategy import cli, ledger
from danus.strategy.config import (
    DEFAULT_CLAUDE_API_FALLBACK, DEFAULT_CLAUDE_API_MODEL,
    load_claude_api_config, resolve_transport,
)
from danus.strategy.transport import ClaudeApiTransport, claude_api_tools_for


@contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _FakeBadRequest(Exception):
    """Stand-in for anthropic.BadRequestError (a 400)."""


def _install_fake_anthropic():
    """Install a fake ``anthropic`` module exposing BadRequestError (the
    transport's lazy import picks it up)."""
    mod = types.ModuleType("anthropic")
    mod.BadRequestError = _FakeBadRequest
    sys.modules["anthropic"] = mod
    return mod


def _block(**kw):
    return types.SimpleNamespace(**kw)


def _final(text="the strategy", thinking="because reasons", model=None,
           stop_reason="end_turn", in_tok=1200, out_tok=3400, web_calls=1,
           cache_read=0, cache_creation=0):
    content = []
    if thinking is not None:
        content.append(_block(type="thinking", thinking=thinking))
    for _ in range(web_calls):
        content.append(_block(type="server_tool_use", name="web_search"))
    if text is not None:
        content.append(_block(type="text", text=text))
    return types.SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        model=model or DEFAULT_CLAUDE_API_MODEL,
        usage=types.SimpleNamespace(
            input_tokens=in_tok, output_tokens=out_tok,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_creation,
        ),
    )


class _Stream:
    """Context-manager stub for ``messages.stream(...)``."""

    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter([_block(type="content_block_delta")])

    def get_final_message(self):
        return self._final


class _StubClient:
    """Records every stream call; serves canned finals in order (last repeats).
    ``beta_raises`` simulates an old SDK (TypeError on the fallbacks kwarg);
    ``plain_error``/``beta_error`` raise from the respective namespace."""

    def __init__(self, finals, *, beta_raises=False, plain_error=None,
                 beta_error=None):
        self.finals = list(finals)
        self.calls = []
        outer = self

        class _Messages:
            def stream(self, **kwargs):
                outer.calls.append({"ns": "plain", "kwargs": kwargs})
                if plain_error is not None:
                    raise plain_error
                return _Stream(outer._next())

        class _BetaMessages:
            def stream(self, **kwargs):
                outer.calls.append({"ns": "beta", "kwargs": kwargs})
                if beta_raises:
                    raise TypeError("unexpected keyword argument 'fallbacks'")
                if beta_error is not None:
                    raise beta_error
                return _Stream(outer._next())

        self.messages = _Messages()
        self.beta = types.SimpleNamespace(messages=_BetaMessages())

    def _next(self):
        return self.finals.pop(0) if len(self.finals) > 1 else self.finals[0]


def _config(**over):
    defaults = dict(api_key="k", base_url=None, model=DEFAULT_CLAUDE_API_MODEL,
                    fallback_model=DEFAULT_CLAUDE_API_FALLBACK,
                    price_in=10.0, price_out=50.0, timeout=60.0)
    defaults.update(over)
    from danus.strategy.config import ClaudeApiConfig
    return ClaudeApiConfig(**defaults)


def _consult(transport, **kw):
    args = dict(effort="xhigh", tools="auto", max_output_tokens=64000)
    args.update(kw)
    return transport.consult("prove the lemma", **args)


# ---- envelope -----------------------------------------------------------------


def test_envelope_success():
    _install_fake_anthropic()
    client = _StubClient([_final()])
    res = _consult(ClaudeApiTransport(_config(), client_factory=lambda: client))
    assert res["transport"] == "claude_api"
    assert res["status"] == "completed"
    assert res["attempt"] == "full"
    assert res["reply"] == "the strategy"
    assert res["reasoning_summary"] == "because reasons"
    assert res["tool_calls"] == ["web_search"]
    assert res["usage"] == {"input": 1200, "output": 3400, "reasoning": None}
    # REAL usage × per-1M rate: 1200/1e6*10 + 3400/1e6*50 = 0.012 + 0.17
    assert res["cost_usd"] == 0.182
    assert res["model"] == DEFAULT_CLAUDE_API_MODEL


def test_cache_tokens_count_as_input():
    _install_fake_anthropic()
    client = _StubClient([_final(in_tok=100, cache_read=900, cache_creation=50)])
    res = _consult(ClaudeApiTransport(_config(), client_factory=lambda: client))
    assert res["usage"]["input"] == 1050


def test_request_shape_full_attempt():
    _install_fake_anthropic()
    client = _StubClient([_final()])
    _consult(ClaudeApiTransport(_config(), client_factory=lambda: client),
             effort="minimal", tools="web", max_output_tokens=999999)
    kw = client.calls[0]["kwargs"]
    assert kw["model"] == DEFAULT_CLAUDE_API_MODEL
    assert kw["system"]  # the advisor system prompt rides on every request
    assert kw["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert kw["output_config"] == {"effort": "low"}  # "minimal" normalized
    assert kw["tools"] == [{"type": "web_search_20260209", "name": "web_search"}]
    assert kw["max_tokens"] == 128000  # clamped to the API ceiling
    assert kw["messages"] == [{"role": "user", "content": "prove the lemma"}]


def test_tools_none_omits_tools_param():
    _install_fake_anthropic()
    client = _StubClient([_final(web_calls=0)])
    res = _consult(ClaudeApiTransport(_config(), client_factory=lambda: client),
                   tools="none")
    assert "tools" not in client.calls[0]["kwargs"]
    assert res["tool_calls"] == []


# ---- refusal-fallback wiring ----------------------------------------------------


def test_fallback_param_attached_by_default():
    _install_fake_anthropic()
    client = _StubClient([_final()])
    _consult(ClaudeApiTransport(_config(), client_factory=lambda: client))
    call = client.calls[0]
    assert call["ns"] == "beta"
    assert call["kwargs"]["betas"] == ["server-side-fallback-2026-06-01"]
    assert call["kwargs"]["fallbacks"] == [{"model": DEFAULT_CLAUDE_API_FALLBACK}]


def test_fallback_disabled_uses_plain_namespace():
    _install_fake_anthropic()
    client = _StubClient([_final()])
    _consult(ClaudeApiTransport(_config(fallback_model=None),
                                client_factory=lambda: client))
    assert client.calls[0]["ns"] == "plain"
    assert "fallbacks" not in client.calls[0]["kwargs"]


def test_fallback_skipped_when_same_as_model():
    _install_fake_anthropic()
    client = _StubClient([_final()])
    _consult(ClaudeApiTransport(_config(model="claude-opus-4-8",
                                        fallback_model="claude-opus-4-8"),
                                client_factory=lambda: client))
    assert client.calls[0]["ns"] == "plain"


def test_old_sdk_typeerror_degrades_to_plain():
    _install_fake_anthropic()
    client = _StubClient([_final()], beta_raises=True)
    res = _consult(ClaudeApiTransport(_config(), client_factory=lambda: client))
    assert [c["ns"] for c in client.calls] == ["beta", "plain"]
    assert res["status"] == "completed"


def test_fell_back_model_is_reported():
    _install_fake_anthropic()
    client = _StubClient([_final(model="claude-opus-4-8")])
    res = _consult(ClaudeApiTransport(_config(), client_factory=lambda: client))
    assert res["model"] == f"claude-opus-4-8 (fell back from {DEFAULT_CLAUDE_API_MODEL})"


# ---- step-down ladder / statuses ------------------------------------------------


def test_step_down_on_400():
    _install_fake_anthropic()
    calls = []

    class _SteppingClient(_StubClient):
        def __init__(self):
            super().__init__([_final()])
            outer = self

            class _Messages:
                def stream(self, **kwargs):
                    calls.append(kwargs)
                    if "tools" in kwargs:  # reject the tool-bearing attempts
                        raise _FakeBadRequest("400 tools")
                    return _Stream(_final(web_calls=0))

            self.messages = _Messages()

    client = _SteppingClient()
    res = _consult(ClaudeApiTransport(_config(fallback_model=None),
                                      client_factory=lambda: client))
    assert res["attempt"] == "no-tools"
    assert res["status"] == "completed"
    assert "tools" in calls[0] and "tools" not in calls[1]


def test_all_attempts_400_raises():
    _install_fake_anthropic()
    client = _StubClient([_final()], plain_error=_FakeBadRequest("400 always"))
    try:
        _consult(ClaudeApiTransport(_config(fallback_model=None),
                                    client_factory=lambda: client))
    except _FakeBadRequest:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected the last 400 to surface")
    assert len(client.calls) == 4  # full / no-tools / no-thinking / bare


def test_refusal_status():
    _install_fake_anthropic()
    client = _StubClient([_final(text=None, thinking=None, web_calls=0,
                                 stop_reason="refusal", out_tok=0)])
    res = _consult(ClaudeApiTransport(_config(), client_factory=lambda: client))
    assert res["status"] == "refusal"
    assert res["reply"] == ""


def test_pause_turn_is_continued():
    _install_fake_anthropic()
    part1 = _final(text="first half, ", stop_reason="pause_turn",
                   in_tok=1000, out_tok=100)
    part2 = _final(text="second half", stop_reason="end_turn",
                   in_tok=1100, out_tok=200, web_calls=0)
    client = _StubClient([part1, part2])
    res = _consult(ClaudeApiTransport(_config(fallback_model=None),
                                      client_factory=lambda: client))
    assert len(client.calls) == 2
    # the continuation re-sends the paused assistant turn
    msgs = client.calls[1]["kwargs"]["messages"]
    assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
    assert res["reply"] == "first half, second half"
    assert res["status"] == "completed"
    assert res["usage"] == {"input": 2100, "output": 300, "reasoning": None}


# ---- config / transport resolution ----------------------------------------------


def test_resolve_transport_accepts_claude_api():
    with _env(DANUS_CONSULT_TRANSPORT=None):
        assert resolve_transport("claude_api") == "claude_api"
    with _env(DANUS_CONSULT_TRANSPORT="claude_api"):
        assert resolve_transport(None) == "claude_api"


def test_load_config_env_and_key_fallback():
    with _env(DANUS_CONSULT_CLAUDE_API_KEY=None, ANTHROPIC_API_KEY="plain-key",
              DANUS_CONSULT_CLAUDE_API_MODEL=None,
              DANUS_CONSULT_CLAUDE_API_FALLBACK=None,
              DANUS_CONSULT_CLAUDE_API_PRICE_IN="5",
              DANUS_CONSULT_CLAUDE_API_PRICE_OUT="25"):
        cfg = load_claude_api_config()
        assert cfg.api_key == "plain-key"  # ANTHROPIC_API_KEY fallback
        assert cfg.model == DEFAULT_CLAUDE_API_MODEL
        assert cfg.fallback_model == DEFAULT_CLAUDE_API_FALLBACK
        assert (cfg.price_in, cfg.price_out) == (5.0, 25.0)
    with _env(DANUS_CONSULT_CLAUDE_API_KEY="mine", ANTHROPIC_API_KEY="plain-key",
              DANUS_CONSULT_CLAUDE_API_FALLBACK="off"):
        cfg = load_claude_api_config()
        assert cfg.api_key == "mine"  # dedicated knob wins
        assert cfg.fallback_model is None  # "off" disables


# ---- CLI branch ------------------------------------------------------------------


def _run_cli(argv, stdin_text="the elaboration"):
    """Run cli.main with a prompt file; returns (exit_code, parsed_stdout_json)."""
    import io
    from contextlib import redirect_stdout

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prompt.md"
        p.write_text(stdin_text, encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--file", str(p), *argv])
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        return code, (json.loads(lines[-1]) if lines else None)


def test_cli_missing_key_exits_3():
    with _env(DANUS_CONSULT_CLAUDE_API_KEY=None, ANTHROPIC_API_KEY=None):
        code, _ = _run_cli(["--transport", "claude_api"])
        assert code == 3


def test_cli_success_and_ledger():
    _install_fake_anthropic()
    client = _StubClient([_final()])
    orig = cli.ClaudeApiTransport
    cli.ClaudeApiTransport = (
        lambda cfg: ClaudeApiTransport(cfg, client_factory=lambda: client))
    try:
        with tempfile.TemporaryDirectory() as proj, \
             _env(DANUS_CONSULT_CLAUDE_API_KEY="k",
                  DANUS_CONSULT_CLAUDE_API_MODEL=None,
                  DANUS_CONSULT_CLAUDE_API_FALLBACK=None):
            code, res = _run_cli(["--transport", "claude_api", "--quiet",
                                  "--project", proj])
            assert code == 0
            assert res["status"] == "completed"
            assert res["cost_usd"] == 0.182
            assert float(res["project_total_usd"]) == 0.182
            events = [json.loads(l) for l in
                      (Path(proj) / "spend" / "consult.jsonl").read_text().splitlines()]
            assert events[-1]["cost_usd"] == 0.182
    finally:
        cli.ClaudeApiTransport = orig


def test_cli_refusal_exits_1():
    _install_fake_anthropic()
    client = _StubClient([_final(text=None, thinking=None, web_calls=0,
                                 stop_reason="refusal", out_tok=0)])
    orig = cli.ClaudeApiTransport
    cli.ClaudeApiTransport = (
        lambda cfg: ClaudeApiTransport(cfg, client_factory=lambda: client))
    try:
        with _env(DANUS_CONSULT_CLAUDE_API_KEY="k"):
            code, res = _run_cli(["--transport", "claude_api", "--quiet"])
            assert code == 1
            assert res["status"] == "refusal"
    finally:
        cli.ClaudeApiTransport = orig


def test_tools_for_modes():
    assert claude_api_tools_for("none") == []
    assert claude_api_tools_for("web") == claude_api_tools_for("auto")


def _main():  # standalone runner, mirroring the sibling suites
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _main()
