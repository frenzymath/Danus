"""Offline tests for danus.strategy — no network, no OpenAI package, no spend.

We stub the OpenAI Responses client (a fake ``client.responses.create`` that
yields streamed events) and the ``openai.BadRequestError`` type, so the transport
layer, envelope shaping, cost math, 400 step-down ordering, and the ledger are all
exercised with zero external dependency.

Runs standalone (``python -m danus.strategy.tests.test_strategy``) and under pytest.
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
    DEFAULT_CLAUDE_CODE_MODEL, DEFAULT_MODEL, DEFAULT_PRICE_IN, DEFAULT_PRICE_OUT,
    ClaudeCodeConfig, ConsultConfig, load_claude_code_config, load_config, resolve_transport,
)
from danus.strategy.transport import (
    GptProTransport, ClaudeCodeTransport, OffTransport, Transport,
    claude_tools_for, shape_envelope, tools_for,
)


# ---- fake OpenAI object graph -------------------------------------------------

class _Summary:
    def __init__(self, text):
        self.text = text


class _Item:
    def __init__(self, type, summary=None):
        self.type = type
        self.summary = [_Summary(s) for s in (summary or [])]


class _Usage:
    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return self._d


class _Response:
    def __init__(self, output_text="", output=None, usage=None, status="completed"):
        self.output_text = output_text
        self.output = output or []
        self.usage = _Usage(usage) if usage is not None else None
        self.status = status


class _Event:
    def __init__(self, type, response=None):
        self.type = type
        self.response = response


class _FakeBadRequest(Exception):
    """Stand-in for openai.BadRequestError (a 400)."""


def _install_fake_openai(create_fn):
    """Install a fake ``openai`` module exposing BadRequestError, and return a
    client factory whose ``responses.create`` delegates to ``create_fn``."""
    mod = types.ModuleType("openai")
    mod.BadRequestError = _FakeBadRequest
    sys.modules["openai"] = mod

    responses = types.SimpleNamespace(create=create_fn)
    client = types.SimpleNamespace(responses=responses)
    return lambda: client


_CFG = ConsultConfig(api_key="k", base_url="http://x", model="gpt-5.5-pro",
                     price_in=31.5, price_out=189.0, timeout=1.0)


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


# ---- tests --------------------------------------------------------------------

def test_envelope_shaping_and_cost():
    final = _Response(
        output_text="the guidance",
        output=[_Item("reasoning", summary=["step a", "step b"]),
                _Item("web_search_call")],
        usage={"input_tokens": 1_000_000, "output_tokens": 2_000_000,
               "output_tokens_details": {"reasoning_tokens": 500}},
    )
    env = shape_envelope(final, transport="gpt_pro", model="m", effort="high",
                         attempt="full", seconds=12.34, status="completed",
                         price_in=31.5, price_out=189.0)
    assert env["reply"] == "the guidance"
    assert env["transport"] == "gpt_pro" and env["attempt"] == "full"
    assert env["usage"] == {"input": 1_000_000, "output": 2_000_000, "reasoning": 500}
    assert env["tool_calls"] == ["web_search_call"]
    assert env["reasoning_summary"] == "step a\n\n---\n\nstep b"
    # cost = 1M/1e6*31.5 + 2M/1e6*189 = 31.5 + 378 = 409.5
    assert env["cost_usd"] == 409.5
    assert env["seconds"] == 12.3


def test_envelope_none_final_is_wellformed():
    env = shape_envelope(None, transport="gpt_pro", model="m", effort="high",
                         attempt="bare", seconds=1.0, status="failed",
                         price_in=31.5, price_out=189.0)
    assert env["reply"] == "" and env["cost_usd"] == 0.0
    assert env["usage"] == {"input": 0, "output": 0, "reasoning": None}


def test_api_transport_completed():
    resp = _Response(output_text="hi", usage={"input_tokens": 10, "output_tokens": 20})

    def create(**kw):
        assert kw["background"] is True and kw["stream"] is True
        return iter([_Event("response.completed", response=resp)])

    factory = _install_fake_openai(create)
    env = GptProTransport(_CFG, client_factory=factory).consult(
        "prompt", effort="high", tools="auto", max_output_tokens=100)
    assert env["status"] == "completed" and env["reply"] == "hi"
    assert env["attempt"] == "full"


def test_step_down_ordering_on_400():
    """The first two attempts (full, no-tools) 400; no-effort succeeds. Verifies
    step-down order and that we stop at the first non-400."""
    seen = []

    def create(**kw):
        has_effort = "effort" in (kw.get("reasoning") or {})
        has_tools = bool(kw.get("tools"))
        if has_effort and has_tools:
            seen.append("full")
            raise _FakeBadRequest("400 full")
        if has_effort and not has_tools:
            seen.append("no-tools")
            raise _FakeBadRequest("400 no-tools")
        seen.append("no-effort")
        return iter([_Event("response.completed",
                            response=_Response(output_text="ok", usage={"input_tokens": 1, "output_tokens": 1}))])

    factory = _install_fake_openai(create)
    env = GptProTransport(_CFG, client_factory=factory).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert seen == ["full", "no-tools", "no-effort"]
    assert env["attempt"] == "no-effort" and env["reply"] == "ok"


def test_non_400_error_surfaces():
    class _Timeout(Exception):
        pass

    def create(**kw):
        raise _Timeout("connection dropped")

    factory = _install_fake_openai(create)
    try:
        GptProTransport(_CFG, client_factory=factory).consult(
            "p", effort="high", tools="auto", max_output_tokens=10)
        assert False, "a non-400 error must surface, not step down"
    except _Timeout:
        pass


def test_tools_for():
    assert tools_for("none") == []
    assert [t["type"] for t in tools_for("web")] == ["web_search"]
    assert [t["type"] for t in tools_for("auto")] == ["web_search", "code_interpreter"]


def test_off_transport_short_circuit():
    env = OffTransport().consult("p", effort="high", tools="auto", max_output_tokens=10)
    assert env["transport"] == "off" and env["reply"] == "" and env["cost_usd"] == 0.0
    assert env["status"] == "disabled"


def test_ledger_append_and_total():
    with tempfile.TemporaryDirectory() as tmp:
        e1 = {"model": "m", "effort": "high", "attempt": "full", "status": "completed",
              "usage": {"input": 1, "output": 2, "reasoning": 3}, "cost_usd": 1.5, "seconds": 1.0}
        e2 = dict(e1); e2["cost_usd"] = 2.25
        t1 = ledger.log_spend(tmp, e1)
        t2 = ledger.log_spend(tmp, e2)
        assert t1 == "1.5000" and t2 == "3.7500"
        path = ledger.ledger_path(tmp)
        lines = path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["cost_usd"] == 1.5


def test_ledger_tolerates_malformed_lines():
    with tempfile.TemporaryDirectory() as tmp:
        path = ledger.ledger_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cost_usd": 1.0}\ngarbage not json\n{"cost_usd": "bad"}\n')
        total = ledger.log_spend(tmp, {"cost_usd": 0.5, "usage": {}})
        # 1.0 + (skip garbage) + (skip bad) + 0.5 = 1.5
        assert total == "1.5000"


def test_resolve_transport():
    with _env(DANUS_CONSULT_TRANSPORT=None):
        assert resolve_transport(None) == "gpt_pro"
        assert resolve_transport("off") == "off"
        assert resolve_transport("claude_code") == "claude_code"
    with _env(DANUS_CONSULT_TRANSPORT="off"):
        assert resolve_transport(None) == "off"
        assert resolve_transport("gpt_pro") == "gpt_pro"  # CLI wins
    with _env(DANUS_CONSULT_TRANSPORT="claude_code"):
        assert resolve_transport(None) == "claude_code"  # env recognised
    # only 'gpt_pro', 'off', 'claude' exist; any other value resolves to the gpt_pro default
    with _env(DANUS_CONSULT_TRANSPORT="something-else"):
        assert resolve_transport(None) == "gpt_pro"


def test_load_config_env():
    with _env(DANUS_CONSULT_API_KEY="ck", DANUS_CONSULT_BASE_URL="http://b",
              DANUS_CONSULT_MODEL="override"):
        cfg = load_config()
        assert cfg.api_key == "ck" and cfg.base_url == "http://b"
        assert cfg.model == "override"  # env model wins over the built-in default


def test_cli_empty_prompt_refused():
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "empty.md"
        pf.write_text("   \n\t\n")  # whitespace-only => empty prompt
        with _env(DANUS_CONSULT_TRANSPORT="off"):
            rc = cli.main(["--file", str(pf)])
    assert rc == 2


def test_cli_off_short_circuit_with_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "prompt.md"
        pf.write_text("elaborate please")
        with _env(DANUS_CONSULT_TRANSPORT="off"):
            rc = cli.main(["--file", str(pf), "--project", tmp])
        assert rc == 1  # off => non-zero
        # the $0 entry was still recorded
        assert ledger.ledger_path(tmp).exists()
        rec = json.loads(ledger.ledger_path(tmp).read_text().splitlines()[0])
        assert rec["cost_usd"] == 0.0


def test_cli_missing_key_when_api():
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "p.md"
        pf.write_text("hello")
        with _env(DANUS_CONSULT_TRANSPORT="gpt_pro", DANUS_CONSULT_API_KEY=None):
            rc = cli.main(["--file", str(pf)])
        assert rc == 3


# ---- transport: base class, default client, stream branches ------------------

def test_base_transport_consult_not_implemented():
    """The abstract Transport.consult is a stub that must be overridden."""
    try:
        Transport().consult("p", effort="high", tools="auto", max_output_tokens=1)
        assert False, "abstract Transport.consult must raise NotImplementedError"
    except NotImplementedError:
        pass


def test_default_client_builds_from_config():
    """`_default_client` lazily imports openai and constructs OpenAI(...) with the
    config's key/base_url/timeout. We inject a fake `openai.OpenAI` capturing the
    kwargs — no network, no real package."""
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    mod = types.ModuleType("openai")
    mod.OpenAI = _FakeOpenAI
    mod.BadRequestError = _FakeBadRequest
    old = sys.modules.get("openai")
    sys.modules["openai"] = mod
    try:
        # GptProTransport with NO client_factory => uses _default_client
        client = GptProTransport(_CFG)._client_factory()
    finally:
        if old is not None:
            sys.modules["openai"] = old
        else:
            sys.modules.pop("openai", None)
    assert isinstance(client, _FakeOpenAI)
    assert captured == {"api_key": "k", "base_url": "http://x", "timeout": 1.0}


def test_run_stream_failed_response_branch():
    """A `response.failed` event must set final=that response and status='failed'
    (the incomplete/failed branch), producing a well-formed non-completed envelope."""
    failed = _Response(output_text="", usage=None, status="failed")

    def create(**kw):
        return iter([
            _Event("response.in_progress", response=_Response(status="in_progress")),
            _Event("response.failed", response=failed),
        ])

    factory = _install_fake_openai(create)
    env = GptProTransport(_CFG, client_factory=factory).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "failed"
    assert env["reply"] == "" and env["cost_usd"] == 0.0


def test_run_stream_incomplete_carries_response_status():
    """`response.incomplete` sets final to the event's response and takes its
    `status` attribute ('incomplete'), still shaping a well-formed envelope with the
    partial reply/usage."""
    resp = _Response(output_text="partial", usage={"input_tokens": 1, "output_tokens": 1},
                     status="incomplete")

    def create(**kw):
        return iter([_Event("response.incomplete", response=resp)])

    factory = _install_fake_openai(create)
    env = GptProTransport(_CFG, client_factory=factory).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "incomplete"
    assert env["reply"] == "partial"


def test_on_progress_heartbeat_fires_on_completed():
    """The heartbeat callback fires on the completed event (elapsed, status, n)."""
    beats = []
    resp = _Response(output_text="ok", usage={"input_tokens": 1, "output_tokens": 1})

    def create(**kw):
        return iter([
            _Event("response.created", response=_Response(status="queued")),
            _Event("response.completed", response=resp),
        ])

    factory = _install_fake_openai(create)
    env = GptProTransport(_CFG, client_factory=factory).consult(
        "p", effort="high", tools="auto", max_output_tokens=10,
        on_progress=lambda elapsed, status, n: beats.append((elapsed, status, n)))
    assert env["status"] == "completed"
    assert len(beats) == 1
    elapsed, status, n = beats[0]
    assert status == "completed" and n == 2 and elapsed >= 0.0


def test_all_attempts_400_reraises_last():
    """Every step-down attempt 400s => the last BadRequestError surfaces (never a
    silent empty result)."""
    seen = []

    def create(**kw):
        seen.append(1)
        raise _FakeBadRequest(f"400 #{len(seen)}")

    factory = _install_fake_openai(create)
    try:
        GptProTransport(_CFG, client_factory=factory).consult(
            "p", effort="high", tools="auto", max_output_tokens=10)
        assert False, "when all 4 attempts 400 the last error must be re-raised"
    except _FakeBadRequest as e:
        assert "400 #4" in str(e)
    assert len(seen) == 4  # full, no-tools, no-effort, bare


# ---- cli: _write_out, off+out, gpt_pro success path -------------------------------

def test_cli_off_writes_markdown_out():
    """--out on the off path writes a markdown dump (exercises _write_out)."""
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "p.md"
        pf.write_text("please elaborate")
        out = Path(tmp) / "out.md"
        with _env(DANUS_CONSULT_TRANSPORT="off"):
            rc = cli.main(["--file", str(pf), "--out", str(out)])
        assert rc == 1
        md = out.read_text(encoding="utf-8")
        assert "transport=off" in md
        assert "## reply (record this as master_guidance)" in md
        assert "_(none)_" in md  # empty reasoning summary rendered as placeholder


def test_cli_api_success_full_path(capsys):
    """CLI gpt_pro path with a completed response: heartbeat runs, ledger records the
    real cost, --out writes markdown, JSON envelope on stdout, rc 0."""
    resp = _Response(
        output_text="the guidance",
        output=[_Item("reasoning", summary=["did a thing"]), _Item("web_search_call")],
        usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )

    def create(**kw):
        assert kw["background"] is True and kw["stream"] is True
        return iter([_Event("response.completed", response=resp)])

    factory = _install_fake_openai(create)
    # patch GptProTransport so cli.main's `GptProTransport(config)` uses our fake client
    orig_init = GptProTransport.__init__

    def patched_init(self, config, client_factory=None):
        orig_init(self, config, client_factory=factory)

    GptProTransport.__init__ = patched_init
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "p.md"
            pf.write_text("hello")
            out = Path(tmp) / "out.md"
            with _env(DANUS_CONSULT_TRANSPORT="gpt_pro", DANUS_CONSULT_API_KEY="ck",
                      DANUS_CONSULT_BASE_URL=None, DANUS_CONSULT_MODEL=None,
                      DANUS_CONSULT_PRICE_IN=None, DANUS_CONSULT_PRICE_OUT=None):
                rc = cli.main(["--file", str(pf), "--project", tmp, "--out", str(out)])
            assert rc == 0
            captured = capsys.readouterr()
            env = json.loads(captured.out.strip())
            assert env["reply"] == "the guidance" and env["status"] == "completed"
            # cost = 1M/1e6*31.5 + 1M/1e6*189 = 220.5
            assert env["cost_usd"] == 220.5
            assert env["project_total_usd"] == "220.5000"
            # heartbeat printed to stderr (not --quiet)
            assert "[consult" in captured.err
            assert "the guidance" in out.read_text(encoding="utf-8")
            # ledger recorded the real cost
            rec = json.loads(ledger.ledger_path(tmp).read_text().splitlines()[0])
            assert rec["cost_usd"] == 220.5
    finally:
        GptProTransport.__init__ = orig_init


def test_cli_api_warns_on_non_completed_status(capsys):
    """A non-completed status on the gpt_pro path emits a WARNING to stderr, rc still 0."""
    resp = _Response(output_text="partial", usage={"input_tokens": 1, "output_tokens": 1},
                     status="incomplete")

    def create(**kw):
        return iter([_Event("response.incomplete", response=resp)])

    factory = _install_fake_openai(create)
    orig_init = GptProTransport.__init__

    def patched_init(self, config, client_factory=None):
        orig_init(self, config, client_factory=factory)

    GptProTransport.__init__ = patched_init
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "p.md"
            pf.write_text("hello")
            with _env(DANUS_CONSULT_TRANSPORT="gpt_pro", DANUS_CONSULT_API_KEY="ck",
                      DANUS_CONSULT_BASE_URL=None):
                rc = cli.main(["--file", str(pf), "--quiet"])
            assert rc == 0
            err = capsys.readouterr().err
            assert "WARNING status=" in err
    finally:
        GptProTransport.__init__ = orig_init


def test_cli_stdin_source(capsys, monkeypatch):
    """--stdin reads the prompt from stdin (the non---file source branch)."""
    monkeypatch.setattr(sys, "stdin", io_stringio("from stdin\n"))
    with _env(DANUS_CONSULT_TRANSPORT="off"):
        rc = cli.main(["--stdin"])
    assert rc == 1
    assert '"transport": "off"' in capsys.readouterr().out


def io_stringio(s):
    import io
    return io.StringIO(s)


# ---- config: _float fallbacks -------------------------------------------------

def test_load_config_float_defaults_and_parse():
    """Missing price env => defaults; unparseable price env => default (ValueError
    swallowed); valid => parsed."""
    with _env(DANUS_CONSULT_PRICE_IN=None, DANUS_CONSULT_PRICE_OUT=None,
              DANUS_CONSULT_TIMEOUT=None):
        cfg = load_config()
        assert cfg.price_in == DEFAULT_PRICE_IN and cfg.price_out == DEFAULT_PRICE_OUT
        assert cfg.timeout == 7200.0
        assert cfg.model == DEFAULT_MODEL and cfg.has_key is False
    with _env(DANUS_CONSULT_PRICE_IN="not-a-number", DANUS_CONSULT_PRICE_OUT="12.5"):
        cfg = load_config()
        assert cfg.price_in == DEFAULT_PRICE_IN  # ValueError => default
        assert cfg.price_out == 12.5


# ---- ledger: blank-line skip --------------------------------------------------

def test_ledger_skips_blank_lines():
    """Blank lines in the ledger are skipped by the sum (the `if not line` branch)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = ledger.ledger_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cost_usd": 2.0}\n\n   \n{"cost_usd": 1.0}\n')
        total = ledger.log_spend(tmp, {"cost_usd": 0.5, "usage": {}})
        assert total == "3.5000"  # 2.0 + 1.0 + 0.5, blanks skipped


# ---- __main__ entry point -----------------------------------------------------

def test_main_module_entry_point():
    """`python -m danus.strategy` runs cli.main and propagates its exit code.
    Run in-process via runpy (so coverage sees __main__.py) with argv/stdin patched
    and the off transport => rc 1 raised as SystemExit."""
    import runpy
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "p.md"
        pf.write_text("hi")
        old_argv = sys.argv
        sys.argv = ["danus.strategy", "--file", str(pf)]
        try:
            with _env(DANUS_CONSULT_TRANSPORT="off"):
                try:
                    runpy.run_module("danus.strategy", run_name="__main__")
                    assert False, "entry point must sys.exit with the CLI rc"
                except SystemExit as e:
                    assert e.code == 1  # off => rc 1
        finally:
            sys.argv = old_argv


# ---- claude-subscription transport (offline, stubbed `claude -p`) -------------

def test_claude_tools_for():
    # every mode -> web-only allowlist; never empty (claude --tools "" enables ALL
    # tools) and never Bash — see danus/strategy/tests/test_claude_code_transport.py.
    for mode in ("none", "web", "auto"):
        assert claude_tools_for(mode) == ["WebSearch", "WebFetch"]


def test_load_claude_code_config_defaults_and_overrides():
    with _env(DANUS_CONSULT_CLAUDE_CODE_MODEL=None, DANUS_CONSULT_CLAUDE_CODE_BIN=None,
              DANUS_CONSULT_CLAUDE_CODE_MAX_WALL=None):
        cfg = load_claude_code_config()
        assert isinstance(cfg, ClaudeCodeConfig)
        assert cfg.model == DEFAULT_CLAUDE_CODE_MODEL and cfg.claude_bin == "claude"
        assert cfg.max_wall == 1800.0
    with _env(DANUS_CONSULT_CLAUDE_CODE_MODEL="claude-opus-9", DANUS_CONSULT_CLAUDE_CODE_BIN="/opt/claude",
              DANUS_CONSULT_CLAUDE_CODE_MAX_WALL="42.5"):
        cfg = load_claude_code_config()
        assert cfg.model == "claude-opus-9" and cfg.claude_bin == "/opt/claude"
        assert cfg.max_wall == 42.5
    with _env(DANUS_CONSULT_CLAUDE_CODE_MAX_WALL="not-a-number"):
        assert load_claude_code_config().max_wall == 1800.0  # ValueError => default


def _claude_result_line(**over):
    """A minimal `claude -p --output-format json` result object as a JSON line."""
    d = {
        "result": "the strategy",
        "is_error": False,
        "subtype": "success",
        "modelUsage": {"claude-fable-5": {"outputTokens": 100},
                       "claude-haiku": {"outputTokens": 9999}},
        "usage": {"input_tokens": 50, "output_tokens": 200,
                  "server_tool_use": {"web_search_requests": 3}},
        "duration_ms": 4200,
    }
    d.update(over)
    return json.dumps(d)


def test_claude_code_transport_success():
    """A well-formed `claude -p` JSON result => completed envelope with the metered
    cost (tokens × the configured per-1M rate), the non-haiku model picked as the
    responder, web_search tool_calls counted."""
    captured = {}

    def runner(cmd, *, input, cwd, env, timeout):
        captured["cmd"] = cmd
        captured["env_has_key"] = "ANTHROPIC_API_KEY" in env
        return types.SimpleNamespace(
            stdout="noise line\n" + _claude_result_line() + "\n", stderr="", returncode=0)

    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "secret"
    try:
        env = ClaudeCodeTransport("claude-fable-5", runner=runner).consult(
            "prompt", effort="high", tools="auto", max_output_tokens=10)
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old
    assert env["transport"] == "claude_code" and env["status"] == "completed"
    assert env["reply"] == "the strategy"
    assert env["cost_usd"] == 0.0105  # 50/1e6*10 + 200/1e6*50 (fable-5 default rates)
    assert env["model"] == "claude-fable-5"  # haiku helper excluded
    assert env["usage"] == {"input": 50, "output": 200, "reasoning": None}
    assert env["tool_calls"] == ["web_search", "web_search", "web_search"]
    assert env["seconds"] == 4.2  # duration_ms / 1000
    # ANTHROPIC_API_KEY scrubbed from the child env (spends subscription, not API)
    assert captured["env_has_key"] is False
    # command carries the advisor system prompt + least-privilege tools
    assert "--append-system-prompt" in captured["cmd"]
    assert "WebSearch" in captured["cmd"] and "Bash" not in captured["cmd"]


def test_claude_code_transport_model_fallback():
    """A requested model absent from modelUsage keys => fell_back annotation."""
    def runner(cmd, *, input, cwd, env, timeout):
        line = _claude_result_line(modelUsage={"claude-opus-9": {"outputTokens": 100}})
        return types.SimpleNamespace(stdout=line, stderr="", returncode=0)

    env = ClaudeCodeTransport("claude-fable-5", runner=runner).consult(
        "p", effort="high", tools="web", max_output_tokens=10)
    assert env["model"] == "claude-opus-9 (fell back from claude-fable-5)"


def test_claude_code_transport_error_subtype():
    """is_error / non-success subtype => status 'error' even with a result string."""
    def runner(cmd, *, input, cwd, env, timeout):
        line = _claude_result_line(is_error=True, result="")
        return types.SimpleNamespace(stdout=line, stderr="", returncode=1)

    env = ClaudeCodeTransport("claude-fable-5", runner=runner).consult(
        "p", effort="high", tools="none", max_output_tokens=10)
    assert env["status"] == "error" and env["reply"] == ""


def test_claude_code_transport_unparseable_stdout():
    """No JSON line on stdout => error envelope (never crashes)."""
    def runner(cmd, *, input, cwd, env, timeout):
        return types.SimpleNamespace(stdout="not json at all\nstill not json\n",
                                     stderr="boom", returncode=1)

    env = ClaudeCodeTransport("claude-fable-5", runner=runner).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "error" and env["reply"] == "" and env["cost_usd"] == 0.0


def test_claude_code_transport_timeout():
    """A subprocess timeout => 'timeout' status envelope with max_wall seconds."""
    import subprocess as _sp

    def runner(cmd, *, input, cwd, env, timeout):
        raise _sp.TimeoutExpired(cmd, timeout)

    env = ClaudeCodeTransport("claude-fable-5", max_wall=12.0, runner=runner).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "timeout" and env["seconds"] == 12.0 and env["reply"] == ""


def test_claude_code_transport_empty_model_usage():
    """Empty modelUsage => requested model, no fallback (the `not keys` branch)."""
    def runner(cmd, *, input, cwd, env, timeout):
        line = _claude_result_line(modelUsage={})
        return types.SimpleNamespace(stdout=line, stderr="", returncode=0)

    env = ClaudeCodeTransport("claude-fable-5", runner=runner).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["model"] == "claude-fable-5"


def test_claude_default_runner_runs_local_subprocess():
    """`_default_runner` (used when no runner is injected) wraps subprocess.run.
    Drive it with a harmless local command — no `claude` binary, no network."""
    import shutil
    echo = shutil.which("echo") or "/bin/echo"
    proc = ClaudeCodeTransport._default_runner(
        [echo, "hi there"], input=None, cwd=None, env=None, timeout=10)
    assert proc.returncode == 0 and "hi there" in proc.stdout


def main() -> None:
    import inspect
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ran = skipped = 0
    for t in tests:
        # standalone runner can't supply pytest fixtures (capsys/monkeypatch); skip
        # those — they are still covered under `pytest`.
        if inspect.signature(t).parameters:
            print(f"  [skip] {t.__name__} (needs pytest fixture)")
            skipped += 1
            continue
        t()
        ran += 1
        print(f"  [ok] {t.__name__}")
    print(f"ALL STRATEGY TESTS PASSED ({ran} run, {skipped} skipped — run under pytest for full coverage)")


if __name__ == "__main__":
    main()
