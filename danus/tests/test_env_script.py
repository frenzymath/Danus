"""Behavioral tests for the shell environment loaded by Danus launchers."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_ENV_SCRIPT = _ROOT / "scripts" / "env.sh"
_CHECK_CODEX = _ROOT / "scripts" / "check-codex.sh"


def _source_env(**values: str | None) -> list[str]:
    env = os.environ.copy()
    for name, value in values.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'. "{_ENV_SCRIPT}" >/dev/null; '
                "printf '%s\\n' \"${CODEX_API_KEY-<unset>}\" "
                "\"${CODEX_BACKEND-<unset>}\" \"$DANUS_MAIN_MODEL\" "
                "\"${CODEX_HOME-<unset>}\""
            ),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


def test_env_defers_authentication_to_native_codex():
    api_key, backend, model, _codex_home = _source_env(
        CODEX_API_KEY="native-test-key",
        CODEX_BACKEND=None,
        CODEX_API_MODEL=None,
        DANUS_MAIN_MODEL=None,
        DANUS_CODEX_MODEL=None,
    )

    assert api_key == "native-test-key"
    assert backend == "<unset>"
    assert model == "gpt-5.6-sol"


def test_env_uses_codex_native_home_by_default():
    _api_key, _backend, _model, codex_home = _source_env(CODEX_HOME=None)

    assert codex_home == "<unset>"


def test_check_codex_uses_native_authentication_status(tmp_path: Path):
    args_path = tmp_path / "args.json"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "open(os.environ['ARGS_PATH'], 'w').write(json.dumps(sys.argv[1:]))\n"
        "print('Logged in using ChatGPT')\n"
        "raise SystemExit(0 if sys.argv[1:] == ['login', 'status'] else 2)\n",
        encoding="utf-8",
    )
    fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env.update(
        DANUS_CODEX_BIN=str(fake_codex),
        DANUS_RUNTIME=str(tmp_path / "runtime"),
        DANUS_AGENTS_ROOT=str(tmp_path / "projects"),
        VERIFIER_RESULTS_DIR=str(tmp_path / "verify-runs"),
        ARGS_PATH=str(args_path),
    )
    for name in ("CODEX_API_KEY", "CODEX_BACKEND", "DANUS_CODEX_API_KEY"):
        env.pop(name, None)

    completed = subprocess.run(
        ["bash", str(_CHECK_CODEX)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "native authentication active" in completed.stdout
    assert args_path.read_text() == '["login", "status"]'
