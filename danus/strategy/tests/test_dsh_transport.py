"""Offline tests for the dsh consult transport (DeepSeek Harness headless).

The subprocess is stubbed via DshTransport's injectable ``runner``, so these
run with no real ``dsh`` binary and no network. Covers the effort mapping
(DeepSeek's off | high | max enum), the command/env/cwd shape, the per-call
DSH_HOME (credentials + settings copied from the deployment home, the
agent-default-model section overridden, reasoningEffort kept only when the
deployment home carries one), the envelope on success/timeout/error, and the
opt-in char-based metering. One end-to-end CLI test drives the real subprocess
path with a fake ``dsh`` script that just echoes.

Runs standalone (``python -m danus.strategy.tests.test_dsh_transport``) and
under pytest. Kept separate from test_strategy.py.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path

from danus.strategy import cli
from danus.strategy.config import DshConfig, resolve_transport
from danus.strategy.transport import DshTransport, _normalize_dsh_effort

_REPO = Path(__file__).resolve().parents[3]


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


@contextmanager
def _scratch():
    """A scratch dir under the repo's gitignored runtime/."""
    root = _REPO / "runtime" / "test-tmp"
    root.mkdir(parents=True, exist_ok=True)
    td = tempfile.mkdtemp(dir=str(root))
    try:
        yield Path(td)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def _src_home(tmp: Path, *, with_effort: bool = True) -> Path:
    src = tmp / "src-home"
    src.mkdir()
    (src / ".credentials.yaml").write_text("key: fake\n", encoding="utf-8")
    effort_line = "  reasoningEffort: max\n" if with_effort else ""
    (src / "settings.yaml").write_text(
        "agent-default-model:\n  provider: deepseek-official\n"
        f"  model: deepseek-v4-pro\n{effort_line}", encoding="utf-8")
    return src


class _Recorder:
    """Injectable runner: records the cmd/env/cwd and returns a canned result."""

    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def __call__(self, cmd, *, input, cwd, env, timeout):
        self.calls.append({"cmd": cmd, "input": input, "cwd": cwd, "env": env,
                           "timeout": timeout})
        return types.SimpleNamespace(stdout=self.stdout, stderr="",
                                     returncode=self.returncode)


# --- effort mapping ---------------------------------------------------------- #

def test_normalize_dsh_effort():
    assert _normalize_dsh_effort("minimal") == "high"
    assert _normalize_dsh_effort("low") == "high"
    assert _normalize_dsh_effort("medium") == "high"
    assert _normalize_dsh_effort("high") == "high"
    assert _normalize_dsh_effort("xhigh") == "max"
    assert _normalize_dsh_effort("max") == "max"
    try:
        _normalize_dsh_effort("bogus")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_resolve_transport_accepts_dsh():
    assert resolve_transport("dsh") == "dsh"
    with _env(DANUS_CONSULT_TRANSPORT="dsh"):
        assert resolve_transport(None) == "dsh"


# --- command shape + per-call home ------------------------------------------- #

def test_dsh_transport_builds_cmd_and_home():
    with _scratch() as tmp, _env(DANUS_RUNTIME=str(tmp / "runtime")):
        src = _src_home(tmp)
        rec = _Recorder(stdout="do X then Y\n")
        cfg = DshConfig(dsh_bin="/x/tools/dsh.js", dsh_node="node", home=str(src),
                        model=None, max_wall=60.0, price_in=0.0, price_out=0.0)
        env = DshTransport(cfg, runner=rec).consult(
            "elaboration text", effort="xhigh", tools="auto", max_output_tokens=100)
        assert env["transport"] == "dsh"
        assert env["reply"] == "do X then Y"
        assert env["status"] == "completed"
        assert env["usage"] == {"input": 0, "output": 0, "reasoning": None}
        assert env["cost_usd"] == 0.0  # metering off by default
        call = rec.calls[0]
        # a raw bin.js path runs under the node prefix; the task carries the
        # advisor system prompt + the elaboration
        assert call["cmd"][:2] == ["node", "/x/tools/dsh.js"]
        assert call["cmd"][2:4] == ["--profile", "headless"]
        task = call["cmd"][4]
        assert "strategy advisor" in task and "elaboration text" in task
        # per-call DSH_HOME under $DANUS_RUNTIME/dsh-runs, creds + settings copied
        home = Path(call["env"]["DSH_HOME"])
        assert str(home).startswith(str(tmp / "runtime" / "dsh-runs" / "consult-"))
        assert (home / ".credentials.yaml").read_text(encoding="utf-8") == "key: fake\n"
        settings = (home / "settings.yaml").read_text(encoding="utf-8")
        assert "model: deepseek-v4-pro" in settings
        assert "reasoningEffort: max" in settings          # xhigh -> max
        # ran in a throwaway cwd, not the caller's
        assert Path(call["cwd"]).name.startswith("danus-consult-dsh-")


def test_dsh_model_override_and_no_effort_when_source_lacks_it():
    with _scratch() as tmp, _env(DANUS_RUNTIME=str(tmp / "runtime")):
        src = _src_home(tmp, with_effort=False)   # deployment model: no reasoning tier
        rec = _Recorder(stdout="ok")
        cfg = DshConfig(dsh_bin="dsh", dsh_node="node", home=str(src),
                        model="deepseek-v4-flash", max_wall=60.0,
                        price_in=0.0, price_out=0.0)
        DshTransport(cfg, runner=rec).consult(
            "p", effort="high", tools="none", max_output_tokens=10)
        home = Path(rec.calls[0]["env"]["DSH_HOME"])
        settings = (home / "settings.yaml").read_text(encoding="utf-8")
        assert "model: deepseek-v4-flash" in settings
        # the source had no reasoningEffort -> none is written (model may not
        # support reasoning tiers)
        assert "reasoningEffort" not in settings


# --- failure envelopes -------------------------------------------------------- #

class _TimeoutRunner:
    def __call__(self, cmd, *, input, cwd, env, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)


def test_dsh_timeout_envelope():
    with _scratch() as tmp, _env(DANUS_RUNTIME=str(tmp / "runtime")):
        src = _src_home(tmp)
        cfg = DshConfig(dsh_bin="dsh", dsh_node="node", home=str(src),
                        model=None, max_wall=5.0, price_in=0.0, price_out=0.0)
        env = DshTransport(cfg, runner=_TimeoutRunner()).consult(
            "p", effort="high", tools="none", max_output_tokens=10)
        assert env["status"] == "timeout"
        assert env["reply"] == ""
        assert env["seconds"] == 5.0


def test_dsh_nonzero_exit_is_error():
    with _scratch() as tmp, _env(DANUS_RUNTIME=str(tmp / "runtime")):
        src = _src_home(tmp)
        rec = _Recorder(stdout="partial", returncode=1)
        cfg = DshConfig(dsh_bin="dsh", dsh_node="node", home=str(src),
                        model=None, max_wall=60.0, price_in=0.0, price_out=0.0)
        env = DshTransport(cfg, runner=rec).consult(
            "p", effort="high", tools="none", max_output_tokens=10)
        assert env["status"] == "error"


# --- metering ----------------------------------------------------------------- #

def test_dsh_metering_opt_in_char_estimate():
    with _scratch() as tmp, _env(DANUS_RUNTIME=str(tmp / "runtime")):
        src = _src_home(tmp)
        rec = _Recorder(stdout="ABCD" * 100)          # 400 chars -> 100 "tokens"
        cfg = DshConfig(dsh_bin="dsh", dsh_node="node", home=str(src),
                        model=None, max_wall=60.0, price_in=10.0, price_out=20.0)
        env = DshTransport(cfg, runner=rec).consult(
            "P" * 400, effort="high", tools="none", max_output_tokens=10)
        assert env["usage"] == {"input": 100, "output": 100, "reasoning": None}
        assert env["cost_usd"] == round(100 / 1e6 * 10 + 100 / 1e6 * 20, 4)


# --- end-to-end CLI with a fake dsh binary ------------------------------------ #

def test_cli_dsh_transport_end_to_end():
    with _scratch() as tmp, _env(DANUS_RUNTIME=str(tmp / "runtime")):
        fake = tmp / "fake-dsh"
        fake.write_text("#!/usr/bin/env bash\necho THE-STRATEGY\n", encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        src = _src_home(tmp)
        prompt_file = tmp / "prompt.md"
        prompt_file.write_text("what next?", encoding="utf-8")
        with _env(DANUS_DSH_BIN=str(fake), DANUS_DSH_NODE="",
                  DANUS_DSH_HOME=str(src)):
            rc = cli.main(["--transport", "dsh", "--file", str(prompt_file),
                           "--effort", "high"])
        # rc 0 == the completed path ran (a non-zero rc / uncaught error would
        # fail this); the envelope itself is printed to stdout by the CLI.
        assert rc == 0


def main() -> None:
    tests = [
        test_normalize_dsh_effort,
        test_resolve_transport_accepts_dsh,
        test_dsh_transport_builds_cmd_and_home,
        test_dsh_model_override_and_no_effort_when_source_lacks_it,
        test_dsh_timeout_envelope,
        test_dsh_nonzero_exit_is_error,
        test_dsh_metering_opt_in_char_estimate,
        test_cli_dsh_transport_end_to_end,
    ]
    for t in tests:
        t()
        print(f"  [ok] {t.__name__}")
    print("ALL DSH TRANSPORT TESTS PASSED")


if __name__ == "__main__":
    main()
