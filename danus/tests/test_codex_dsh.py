"""Offline tests for the ``dsh`` codex backend (bin/codex-dsh shim).

No DeepSeek call is ever made: DANUS_DSH_BIN points at a tiny stub that reports
what it received on stdout and prints a canned answer. Covers:

  * the worker-style argv (positional prompt, -C/-c/sandbox flags dropped,
    --model honored for deepseek-ish models, effort mapped xhigh -> max)
  * the authoring stdin form (``-`` sentinel, non-deepseek model falls back
    to the default, --config tools.web_search dropped)
  * the per-run DSH_HOME: the shim reports its path on stderr; the stub echoes
    back the settings.yaml + credentials it found there (the run-home content is
    asserted via child stdout/stderr, never by re-reading child-written files —
    child-file visibility to the test process is not guaranteed in sandboxed
    environments)
  * stdout/exit-code passthrough, exit 127 when dsh is not provisioned,
    exit 2 on an unsupported flag / empty task

Runs standalone (``python -m danus.tests.test_codex_dsh``) and under pytest.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SHIM = _REPO / "bin" / "codex-dsh"

# A fake dsh: reads the per-run settings.yaml + credentials from DSH_HOME and
# prints them back as a RECORD line on stdout (child stdout is always visible to
# the test process), then exits with FAKE_DSH_EXIT. Written as python
# (DANUS_DSH_NODE points at python3).
_STUB_DSH = '''
import json, os, sys
home = os.environ.get("DSH_HOME", "")
settings = open(os.path.join(home, "settings.yaml"), encoding="utf-8").read()
creds = open(os.path.join(home, ".credentials.yaml"), encoding="utf-8").read()
try:
    patch = open(os.path.join(home, "profiles", "headless", "cordis.patch.yml"),
                 encoding="utf-8").read()
    manifest = open(os.path.join(home, "profiles", "headless", "package.json"),
                    encoding="utf-8").read()
except OSError:
    patch = "<missing>"
    manifest = "<missing>"
print("RECORD " + json.dumps({"argv": sys.argv[1:], "settings": settings,
                              "creds": creds, "cwd": os.getcwd(),
                              "patch": patch, "manifest": manifest}))
sys.exit(int(os.environ.get("FAKE_DSH_EXIT", "0")))
'''


@contextlib.contextmanager
def _tmpdir():
    """A scratch dir under the repo's gitignored runtime/."""
    root = _REPO / "runtime" / "test-tmp"
    root.mkdir(parents=True, exist_ok=True)
    td = tempfile.mkdtemp(dir=str(root))
    try:
        yield Path(td)
    finally:
        shutil.rmtree(td, ignore_errors=True)


@contextlib.contextmanager
def _no_runtime_env():
    """runtime/runtime.env (written by scripts/setup-dsh.sh) must not clobber
    the test's own DANUS_DSH_* values when the shim sources scripts/env.sh."""
    envf = _REPO / "runtime" / "runtime.env"
    backup = None
    if envf.exists():
        backup = envf.read_text(encoding="utf-8")
        envf.unlink()
    try:
        yield
    finally:
        if backup is not None:
            envf.write_text(backup, encoding="utf-8")


@contextlib.contextmanager
def _dsh_stub(tmp: Path):
    stub = tmp / "fake-dsh.py"
    stub.write_text("#!/usr/bin/env python3\n" + _STUB_DSH, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    src_home = tmp / "src-home"
    src_home.mkdir()
    (src_home / ".credentials.yaml").write_text("key: fake\n", encoding="utf-8")
    (src_home / "settings.yaml").write_text(
        "provider: decoy-provider\nmodel: decoy-model\n"
        "agent-default-model:\n  provider: deepseek-official\n  model: deepseek-v4-pro\n"
        "  reasoningEffort: max\n", encoding="utf-8")
    runtime = tmp / "runtime"
    worker_dir = tmp / "workers" / "w1"          # worker-style cwd
    worker_dir.mkdir(parents=True)
    yield {
        "stub": stub,
        "src_home": src_home,
        "runtime": runtime,
        "worker_dir": worker_dir,
    }


def _run_shim(*argv, input_text=None, cwd=None, **env_extra):
    py = os.environ.get("DANUS_PY") or "python3"
    env = {
        "CODEX_BACKEND": "dsh",
        "DANUS_RUNTIME": str(env_extra.pop("DANUS_RUNTIME")),
        "DANUS_DSH_HOME": str(env_extra.pop("DANUS_DSH_HOME")),
        "DANUS_DSH_NODE": py,
        "DANUS_DSH_BIN": str(env_extra.pop("DANUS_DSH_BIN")),
        "PATH": os.environ.get("PATH", ""),
    }
    env.update(env_extra)
    return subprocess.run(
        [str(_SHIM), *argv], input=input_text, capture_output=True, text=True,
        env=env, timeout=60, cwd=cwd,
    )


def _record(stdout: str) -> dict:
    assert stdout.startswith("RECORD "), stdout
    return json.loads(stdout.split("RECORD ", 1)[1])


# --- worker-style argv ------------------------------------------------------ #

def test_worker_argv_positional_prompt():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "deepseek-v4-pro",
                "--config", 'model_reasoning_effort="xhigh"',
                "-C", "/some/codex/home",
                "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
                "prove the theorem",
                cwd=s["worker_dir"],
                DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"])
    assert cp.returncode == 0, cp.stderr
    rec = _record(cp.stdout)
    assert rec["argv"] == ["--profile", "headless", "prove the theorem"]
    assert "model: deepseek-v4-pro" in rec["settings"]
    assert "decoy-model" not in rec["settings"].split("agent-default-model:")[-1]
    assert "reasoningEffort: max" in rec["settings"]          # xhigh -> max
    assert "provider: deepseek-official" in rec["settings"]
    assert rec["creds"] == "key: fake\n"
    # the per-run home is under the caller's DANUS_RUNTIME/dsh-runs
    assert f'{s["runtime"]}/dsh-runs/' in cp.stderr
    # the danus gateway MCP is mounted in the per-run headless profile; without a
    # codex -c flag the role defaults to worker — author = the cwd's basename,
    # project dir = the cwd's GRANDPARENT (worker cwd is <project>/workers/<name>)
    assert "dsh-mcp-client" in rec["patch"]
    assert "DANUS_ROLE: 'worker'" in rec["patch"]
    assert "DANUS_AUTHOR: 'w1'" in rec["patch"]
    assert "failOnStartupError: true" in rec["patch"]
    assert '"@deepseek-ai/dsh-headless"' in rec["manifest"]
    assert f"DANUS_PROJECT_DIR: '{tmp}'" in rec["patch"]


# --- authoring stdin form --------------------------------------------------- #

def test_stdin_prompt_and_model_fallback():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "gpt-5.5",
                "--config", 'model_reasoning_effort="high"',
                "-c", 'mcp_servers.danus={command="python3",args=["-m","danus.gateway"],env={DANUS_ROLE="verifier"}}',
                "--config", "tools.web_search=true",
                "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                "-",
                input_text="render this paper",
                DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"])
    assert cp.returncode == 0, cp.stderr
    rec = _record(cp.stdout)
    assert rec["argv"] == ["--profile", "headless", "render this paper"]
    # gpt-5.5 is not a deepseek model -> the source home's model wins
    assert "model: deepseek-v4-pro" in rec["settings"]
    assert "reasoningEffort: high" in rec["settings"]        # high passes through
    assert "tools.web_search" not in rec["settings"]
    # the -c flag carries the gateway role (verifier here): mount with that role,
    # and treat the gateway as an enhancement rather than a boot gate
    assert "DANUS_ROLE: 'verifier'" in rec["patch"]
    assert "failOnStartupError: false" in rec["patch"]


# --- effort mapping --------------------------------------------------------- #

def test_low_effort_maps_to_high():
    # deepseek's reasoning-effort enum is off | high | max: the codex scale's
    # minimal/low/medium tiers all collapse onto high.
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "deepseek-v4-pro",
                "--config", 'model_reasoning_effort="low"',
                "task", DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"])
    assert cp.returncode == 0, cp.stderr
    rec = _record(cp.stdout)
    assert "reasoningEffort: high" in rec["settings"]
    assert "reasoningEffort: low" not in rec["settings"]


# --- failure / passthrough behavior ---------------------------------------- #

def test_exit_code_passthrough():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "deepseek-v4-pro",
                "--config", 'model_reasoning_effort="high"',
                "task", DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"], FAKE_DSH_EXIT="7")
            assert cp.returncode == 7
            assert _record(cp.stdout)["argv"] == ["--profile", "headless", "task"]
            leftover = _leftover_run_homes(Path(s["runtime"]))
            assert leftover == [], leftover


def test_unsupported_flag_fails_loud():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "m", "--config", 'model_reasoning_effort="e"',
                "--definitely-not-a-codex-flag", "task",
                DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"])
    assert cp.returncode == 2
    assert "unsupported codex flag" in cp.stderr


def test_unprovisioned_dsh_exits_127():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "m", "--config", 'model_reasoning_effort="e"',
                "task", DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["runtime"] / "no-such-dsh.js")
    assert cp.returncode == 127
    assert "not provisioned" in cp.stderr


def _leftover_run_homes(runtime: Path) -> list:
    root = runtime / "dsh-runs"
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def test_run_home_is_removed_after_exit():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            cp = _run_shim(
                "exec", "--model", "deepseek-v4-pro",
                "--config", 'model_reasoning_effort="high"',
                "task", cwd=s["worker_dir"],
                DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"])
            assert cp.returncode == 0, cp.stderr
            assert f'{s["runtime"]}/dsh-runs/' in cp.stderr
            leftover = _leftover_run_homes(Path(s["runtime"]))
            assert leftover == [], leftover


def test_gateway_patch_escapes_apostrophe_in_author():
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            nasty = tmp / "workers" / "o'reilly"
            nasty.mkdir(parents=True)
            cp = _run_shim(
                "exec", "--model", "deepseek-v4-pro",
                "--config", 'model_reasoning_effort="high"',
                "task",
                cwd=nasty,
                DANUS_RUNTIME=s["runtime"], DANUS_DSH_HOME=s["src_home"],
                DANUS_DSH_BIN=s["stub"])
    assert cp.returncode == 0, cp.stderr
    rec = _record(cp.stdout)
    assert "DANUS_AUTHOR: 'o''reilly'" in rec["patch"]
    assert "DANUS_ROLE: 'worker'" in rec["patch"]


def test_sigterm_reclaims_run_home():
    """Worker terminate() sends SIGTERM to the shim; the EXIT trap must still
    reclaim the per-run home (exec would have skipped the trap)."""
    with _tmpdir() as tmp, _no_runtime_env():
        with _dsh_stub(tmp) as s:
            slow = tmp / "slow-dsh.py"
            slow.write_text(
                "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n",
                encoding="utf-8")
            slow.chmod(slow.stat().st_mode | stat.S_IXUSR)
            py = os.environ.get("DANUS_PY") or "python3"
            env = {
                "CODEX_BACKEND": "dsh",
                "DANUS_RUNTIME": str(s["runtime"]),
                "DANUS_DSH_HOME": str(s["src_home"]),
                "DANUS_DSH_NODE": py,
                "DANUS_DSH_BIN": str(slow),
                "PATH": os.environ.get("PATH", ""),
            }
            proc = subprocess.Popen(
                [str(_SHIM), "exec", "--model", "deepseek-v4-pro",
                 "--config", 'model_reasoning_effort="high"', "task"],
                cwd=str(s["worker_dir"]), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            time.sleep(0.4)
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            leftover = _leftover_run_homes(Path(s["runtime"]))
            assert leftover == [], leftover


def main() -> None:
    tests = [
        test_worker_argv_positional_prompt,
        test_stdin_prompt_and_model_fallback,
        test_low_effort_maps_to_high,
        test_exit_code_passthrough,
        test_unsupported_flag_fails_loud,
        test_unprovisioned_dsh_exits_127,
        test_run_home_is_removed_after_exit,
        test_gateway_patch_escapes_apostrophe_in_author,
        test_sigterm_reclaims_run_home,
    ]
    for t in tests:
        t()
        print(f"  [ok] {t.__name__}")
    print("ALL CODEX-DSH SHIM TESTS PASSED")


if __name__ == "__main__":
    main()
