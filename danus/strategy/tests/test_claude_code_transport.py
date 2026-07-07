"""Offline tests for the Claude-subscription consult transport (``claude -p``).

The subprocess is stubbed via ClaudeCodeTransport's injectable ``runner``, so these
run with no ``claude`` binary and no network. We assert the command is built with
the isolation flags (bypassPermissions, advisor system prompt, least-privilege
``--tools`` = WebSearch+WebFetch and never Bash), that ANTHROPIC_API_KEY is
scrubbed from the child env, and that the parsed result maps to the pinned
envelope with the metered cost (tokens × the configured per-1M rate).

Runs standalone (``python -m danus.strategy.tests.test_claude_code_transport``) and
under pytest. Kept separate from test_strategy.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path

from danus.strategy import cli, ledger
from danus.strategy.config import (
    DEFAULT_CLAUDE_CODE_MODEL, load_claude_code_config, resolve_transport,
)
from danus.strategy.transport import ClaudeCodeTransport, claude_tools_for


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


def _fake_claude_json(result="the strategy", model="claude-fable-5",
                      in_tok=1200, out_tok=3400, web=2, is_error=False,
                      subtype="success"):
    """A canned `claude -p --output-format json` result line."""
    return json.dumps({
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "result": result,
        "duration_ms": 4200,
        "modelUsage": {model: {"outputTokens": out_tok, "inputTokens": in_tok},
                       "claude-haiku-4-5": {"outputTokens": 10}},
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok,
                  "server_tool_use": {"web_search_requests": web}},
        "total_cost_usd": 0.0,
    })


class _Recorder:
    """Injectable runner: records the cmd/env/cwd and returns a canned result."""

    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def __call__(self, cmd, *, input, cwd, env, timeout):
        self.calls.append({"cmd": cmd, "input": input, "cwd": cwd, "env": env,
                           "timeout": timeout})
        return types.SimpleNamespace(stdout=self.stdout, stderr="", returncode=self.returncode)


# ---- tests --------------------------------------------------------------------

def test_claude_tools_least_privilege():
    # every mode -> the web-only allowlist; NEVER empty (claude --tools "" would
    # enable ALL default tools incl. Bash) and NEVER a file/exec tool.
    for mode in ("auto", "web", "none"):
        allow = claude_tools_for(mode)
        assert allow == ["WebSearch", "WebFetch"]
        assert allow and "" not in allow  # non-empty guards the `--tools ""` trap
        assert "Bash" not in allow and "Write" not in allow


def test_claude_code_transport_builds_cmd_and_envelope():
    rec = _Recorder(_fake_claude_json(result="do X then Y"))
    with _env(ANTHROPIC_API_KEY="sk-x", ANTHROPIC_AUTH_TOKEN="tok-x",
              ANTHROPIC_BASE_URL="https://proxy.example/v1"):
        env = ClaudeCodeTransport("claude-fable-5", claude_bin="claude", runner=rec).consult(
            "elaboration text", effort="xhigh", tools="auto", max_output_tokens=100)
    # envelope shape (matches the pinned uniform envelope)
    assert env["transport"] == "claude_code"
    assert env["reply"] == "do X then Y"
    assert env["cost_usd"] == 0.182  # 1200/1e6*10 + 3400/1e6*50 (fable-5 default rates)
    assert env["status"] == "completed"
    assert env["usage"] == {"input": 1200, "output": 3400, "reasoning": None}
    assert env["tool_calls"] == ["web_search", "web_search"]
    # command flags
    cmd = rec.calls[0]["cmd"]
    assert cmd[0] == "claude" and "-p" in cmd
    assert "--permission-mode" in cmd and "bypassPermissions" in cmd
    assert "--append-system-prompt" in cmd
    assert "--model" in cmd and "claude-fable-5" in cmd
    assert "--output-format" in cmd and "json" in cmd
    # least-privilege tools: web only, never Bash
    assert "WebSearch" in cmd and "WebFetch" in cmd and "Bash" not in cmd
    # settings/MCP isolation: no user-level CLAUDE.md/memory, no user-scope MCP
    i = cmd.index("--setting-sources")
    assert cmd[i + 1] == "" and "--strict-mcp-config" in cmd
    # the prompt travels on STDIN, never argv (argv is world-readable in /proc)
    assert rec.calls[0]["input"] == "elaboration text"
    assert "elaboration text" not in cmd
    # FULL Anthropic auth/routing scrub so the child uses the subscription auth
    child_env = rec.calls[0]["env"]
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        assert k not in child_env
    # ran in a throwaway temp cwd (not the caller's working dir)
    assert Path(rec.calls[0]["cwd"]).name.startswith("danus-consult-")
    assert rec.calls[0]["cwd"] != os.getcwd()


def test_claude_cost_metered_from_configurable_rate():
    # claude cost = input/output tokens × the per-1M rate (like gpt_pro), from the
    # rates passed in (DANUS_CONSULT_CLAUDE_CODE_PRICE_IN/_OUT). NOT hardcoded $0.
    rec = _Recorder(_fake_claude_json())  # usage: input=1200, output=3400
    env = ClaudeCodeTransport("m", price_in=10.0, price_out=20.0, runner=rec).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    # 1200/1e6*10 + 3400/1e6*20 = 0.012 + 0.068 = 0.08
    assert env["cost_usd"] == 0.08
    # a different rate ⇒ a different cost (proves it's not a constant)
    rec2 = _Recorder(_fake_claude_json())
    env2 = ClaudeCodeTransport("m", price_in=0.0, price_out=0.0, runner=rec2).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env2["cost_usd"] == 0.0  # zero rate ⇒ zero, only when explicitly configured so


def test_claude_code_transport_tools_none_is_web_only_never_empty():
    rec = _Recorder(_fake_claude_json())
    ClaudeCodeTransport("m", runner=rec).consult(
        "p", effort="high", tools="none", max_output_tokens=10)
    cmd = rec.calls[0]["cmd"]
    # 'none' maps to web-only, NOT an empty allowlist (which enables all tools)
    i = cmd.index("--tools")
    assert cmd[i + 1:i + 3] == ["WebSearch", "WebFetch"]
    # no empty token in the --tools allowlist (an empty token enables ALL tools);
    # --setting-sources "" earlier in argv is legitimate and out of scope here
    assert "Bash" not in cmd and "" not in cmd[i + 1:]


def test_claude_code_transport_timeout():
    def boom(cmd, *, input, cwd, env, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    env = ClaudeCodeTransport("m", max_wall=5.0, runner=boom).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "timeout" and env["reply"] == "" and env["cost_usd"] == 0.0


def test_claude_effort_minimal_normalized_to_low():
    rec = _Recorder(_fake_claude_json())
    ClaudeCodeTransport("m", runner=rec).consult(
        "p", effort="minimal", tools="auto", max_output_tokens=10)
    cmd = rec.calls[0]["cmd"]
    i = cmd.index("--effort")
    assert cmd[i + 1] == "low"  # "minimal" (not a claude effort) -> "low"


def test_claude_code_transport_fallback_detected():
    # requested Fable, but Opus actually did the work => flagged as a fallback
    rec = _Recorder(_fake_claude_json(model="claude-opus-4-8"))
    env = ClaudeCodeTransport("claude-fable-5", runner=rec).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert "claude-opus-4-8" in env["model"]
    assert "fell back from claude-fable-5" in env["model"]


def test_claude_code_transport_error_result():
    rec = _Recorder(json.dumps({"type": "result", "subtype": "error_max_turns",
                                "is_error": True, "result": ""}))
    env = ClaudeCodeTransport("m", runner=rec).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "error" and env["reply"] == ""
    assert env["cost_usd"] == 0.0


def test_claude_code_transport_no_json_is_error():
    rec = _Recorder("not json at all\nstill not json")
    env = ClaudeCodeTransport("m", runner=rec).consult(
        "p", effort="high", tools="auto", max_output_tokens=10)
    assert env["status"] == "error" and env["reply"] == ""


def test_resolve_transport_claude():
    with _env(DANUS_CONSULT_TRANSPORT=None):
        assert resolve_transport("claude_code") == "claude_code"
    with _env(DANUS_CONSULT_TRANSPORT="claude_code"):
        assert resolve_transport(None) == "claude_code"
        assert resolve_transport("gpt_pro") == "gpt_pro"  # CLI wins


def test_load_claude_code_config_defaults_and_overrides():
    with _env(DANUS_CONSULT_CLAUDE_CODE_MODEL=None, DANUS_CONSULT_CLAUDE_CODE_BIN=None,
              DANUS_CONSULT_CLAUDE_CODE_MAX_WALL=None):
        c = load_claude_code_config()
        assert c.model == DEFAULT_CLAUDE_CODE_MODEL and c.claude_bin == "claude"
        assert c.max_wall == 1800.0
    with _env(DANUS_CONSULT_CLAUDE_CODE_MODEL="claude-opus-4-8",
              DANUS_CONSULT_CLAUDE_CODE_BIN="/opt/claude", DANUS_CONSULT_CLAUDE_CODE_MAX_WALL="600"):
        c = load_claude_code_config()
        assert c.model == "claude-opus-4-8" and c.claude_bin == "/opt/claude"
        assert c.max_wall == 600.0


def test_cli_claude_missing_binary_exit3():
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "p.md"
        pf.write_text("hello")
        with _env(DANUS_CONSULT_TRANSPORT="claude_code",
                  DANUS_CONSULT_CLAUDE_CODE_BIN="/nonexistent/claude-xyz-404"):
            rc = cli.main(["--file", str(pf)])
    assert rc == 3


def test_cli_claude_success_model_override_and_ledger():
    """Drive cli.main through the claude success branch: --model reaches the
    transport, the per-1M rates are wired through, the consult event is recorded to
    the project ledger with the transport's metered cost, and rc == 0."""
    import danus.strategy.cli as climod
    captured = {}

    class _Stub:
        def __init__(self, model, *, claude_bin, max_wall, price_in, price_out):
            captured.update(model=model, claude_bin=claude_bin, max_wall=max_wall,
                            price_in=price_in, price_out=price_out)

        def consult(self, prompt, *, effort, tools, max_output_tokens, on_progress=None):
            return {"transport": "claude_code", "model": captured["model"], "status": "completed",
                    "reply": "guidance", "cost_usd": 0.0105, "effort": effort, "seconds": 1.0,
                    "usage": {"input": 50, "output": 200, "reasoning": None},
                    "tool_calls": [], "reasoning_summary": ""}

    orig_transport, orig_avail = climod.ClaudeCodeTransport, climod._claude_available
    climod.ClaudeCodeTransport = _Stub
    climod._claude_available = lambda b: True
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "p.md"
            pf.write_text("elaborate")
            with _env(DANUS_CONSULT_TRANSPORT="claude_code"):
                rc = cli.main(["--file", str(pf), "--model", "claude-opus-4-8", "--project", tmp])
            assert rc == 0
            assert captured["model"] == "claude-opus-4-8"  # --model override reached transport
            assert captured["price_in"] > 0 and captured["price_out"] > 0  # rates wired through
            rec = json.loads(ledger.ledger_path(tmp).read_text().splitlines()[0])
            assert rec["cost_usd"] == 0.0105  # the transport's metered cost is recorded
    finally:
        climod.ClaudeCodeTransport = orig_transport
        climod._claude_available = orig_avail


def test_cli_claude_noncompleted_returns_1():
    """A non-completed claude consult maps to rc == 1 (main agent reasons alone)."""
    import danus.strategy.cli as climod

    class _Stub:
        def __init__(self, model, *, claude_bin, max_wall, price_in, price_out):
            pass

        def consult(self, prompt, *, effort, tools, max_output_tokens, on_progress=None):
            return {"transport": "claude_code", "model": "m", "status": "error", "reply": "",
                    "cost_usd": 0.0, "effort": effort, "seconds": 0.1,
                    "usage": {"input": 0, "output": 0, "reasoning": None},
                    "tool_calls": [], "reasoning_summary": ""}

    orig_transport, orig_avail = climod.ClaudeCodeTransport, climod._claude_available
    climod.ClaudeCodeTransport = _Stub
    climod._claude_available = lambda b: True
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "p.md"
            pf.write_text("elaborate")
            with _env(DANUS_CONSULT_TRANSPORT="claude_code"):
                rc = cli.main(["--file", str(pf)])
            assert rc == 1
    finally:
        climod.ClaudeCodeTransport = orig_transport
        climod._claude_available = orig_avail


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  [ok] {t.__name__}")
    print(f"ALL CLAUDE-TRANSPORT TESTS PASSED ({len(tests)})")


if __name__ == "__main__":
    main()
