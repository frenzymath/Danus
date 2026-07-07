"""Offline tests for danus.verify.launcher — command shape + subprocess plumbing.

No real codex is ever launched. The subprocess path is exercised by pointing the
codex binary at tiny purpose-built stub scripts written into a temp dir (one per
failure mode) and asserting on the HTTPException status the launcher raises.

Covers:
  * build_codex_command: exec prefix, -C home, -c gateway injection, sandbox flag,
    output path in the prompt, bin resolved via danus.codex.
  * subprocess_env: PATH-prepend for a concrete path; NO cwd injection for bare
    "codex".
  * _allocate_run_id: unique-dir retry on collision (FileExistsError branch).
  * _verification_path: found (each filename) and None-when-absent.
  * run_codex_verification: success readback, 504 timeout, 500 nonzero-exit,
    500 missing-output, 500 bad-json, 500 non-dict-json.

Runs standalone (``python -m danus.verify.tests.test_launcher``) and under pytest.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from danus import codex
from danus.verify import launcher

_STMT = "For every integer n, n + 0 equals n."
_PROOF = "Zero is the additive identity; adding it changes nothing, so n + 0 = n."


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


def _write_stub(dirpath: Path, name: str, body: str) -> Path:
    p = dirpath / name
    p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


# stub that writes a valid verification.json to the prompt's output path
_STUB_OK = """\
import re, sys, json
from pathlib import Path
prompt = sys.argv[-1]
out = Path(re.search(r'this exact path:\\s*(\\S+)', prompt).group(1).rstrip('.'))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"verification_report": {"critical_errors": []},
                           "verdict": "correct", "repair_hints": ""}))
print("ok")
"""

# stub that exits nonzero and writes nothing
_STUB_FAIL = "import sys\nsys.stderr.write('boom\\n')\nsys.exit(7)\n"

# stub that exits 0 but writes NO output file
_STUB_NOOUT = "print('did nothing')\n"

# stub that writes invalid JSON
_STUB_BADJSON = """\
import re, sys
from pathlib import Path
prompt = sys.argv[-1]
out = Path(re.search(r'this exact path:\\s*(\\S+)', prompt).group(1).rstrip('.'))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("{ this is not json ")
"""

# stub that writes valid JSON that is NOT an object (a list)
_STUB_NONDICT = """\
import re, sys, json
from pathlib import Path
prompt = sys.argv[-1]
out = Path(re.search(r'this exact path:\\s*(\\S+)', prompt).group(1).rstrip('.'))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(["not", "a", "dict"]))
"""

# stub that sleeps long enough to trip a 1s timeout
_STUB_SLOW = "import time\ntime.sleep(10)\n"


@contextmanager
def _service(stub_body: str, *, timeout: str = "0"):
    """Point the launcher at a stub codex + isolated results/home dirs."""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        stub = _write_stub(tmpd, "fake.py", stub_body)
        with _env(DANUS_CODEX_BIN=str(stub), CODEX_BIN=None,
                  VERIFIER_RESULTS_DIR=str(tmpd / "runs"),
                  VERIFY_AGENT_HOME=str(tmpd / "home"),
                  CODEX_TIMEOUT_SECONDS=timeout):
            (tmpd / "home").mkdir(exist_ok=True)
            yield


# --------------------------------------------------------------------------- #
# build_codex_command / config resolution                                     #
# --------------------------------------------------------------------------- #

def test_build_codex_command_shape():
    with tempfile.TemporaryDirectory() as tmp:
        with _env(DANUS_CODEX_BIN="/abs/codex",
                  VERIFY_AGENT_HOME=str(tmp),
                  DANUS_VERIFY_MODEL="m-test", DANUS_VERIFY_EFFORT="e-test",
                  DANUS_CODEX_MODEL=None, DANUS_CODEX_EFFORT=None):
            cmd = launcher.build_codex_command("RID", _STMT, _PROOF)
    assert cmd[0] == "/abs/codex" and cmd[1] == "exec"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "m-test"
    assert '--config' in cmd and 'model_reasoning_effort="e-test"' in cmd
    assert "-C" in cmd  # agent home
    # gateway injected via -c with role=verifier
    assert "-c" in cmd
    assert any('mcp_servers.danus=' in a and 'DANUS_ROLE="verifier"' in a for a in cmd)
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    # the prompt (final arg) names the exact output path
    assert cmd[-1].endswith("verification.json.")
    assert "Run_id: RID" in cmd[-1] and _STMT in cmd[-1]


def test_subprocess_env_prepends_dir_for_concrete_path():
    with tempfile.TemporaryDirectory() as tmp:
        binp = str(Path(tmp) / "codex")
        env = codex.subprocess_env(binp)
        assert env["PATH"].split(os.pathsep)[0] == str(Path(tmp).resolve())


def test_subprocess_env_no_cwd_injection_for_bare_name():
    before = os.environ.get("PATH", "")
    env = codex.subprocess_env("codex")
    # bare name has no dir component -> PATH must be untouched (no "." / cwd added)
    assert env["PATH"] == before


# --------------------------------------------------------------------------- #
# _allocate_run_id — collision retry                                          #
# --------------------------------------------------------------------------- #

def test_allocate_run_id_retries_on_collision():
    with tempfile.TemporaryDirectory() as tmp:
        with _env(VERIFIER_RESULTS_DIR=str(Path(tmp) / "runs")):
            base = launcher.generate_run_id(_STMT)
            root = launcher._results_root()
            root.mkdir(parents=True, exist_ok=True)
            # pre-create the base dir so the first mkdir raises FileExistsError,
            # forcing the numeric-suffix retry branch (lines 92-95).
            (root / base).mkdir()
            # generate_run_id is timestamp-based; freeze it so the retry collides
            # deterministically on `base`.
            orig = launcher.generate_run_id
            launcher.generate_run_id = lambda s: base  # type: ignore[assignment]
            try:
                rid = launcher._allocate_run_id(_STMT)
            finally:
                launcher.generate_run_id = orig  # type: ignore[assignment]
            assert rid == f"{base}_2"
            assert (root / rid).is_dir()


# --------------------------------------------------------------------------- #
# _verification_path                                                          #
# --------------------------------------------------------------------------- #

def test_verification_path_found_and_absent():
    with tempfile.TemporaryDirectory() as tmp:
        with _env(VERIFIER_RESULTS_DIR=str(Path(tmp) / "runs")):
            rid = "RID1"
            d = launcher._results_dir(rid)
            d.mkdir(parents=True)
            assert launcher._verification_path(rid) is None  # nothing yet
            (d / launcher.VERIFICATION_FILENAMES[1]).write_text("{}")
            # the alternate filename is also recognized
            assert launcher._verification_path(rid).name == launcher.VERIFICATION_FILENAMES[1]
            (d / launcher.VERIFICATION_FILENAMES[0]).write_text("{}")
            # primary filename takes precedence
            assert launcher._verification_path(rid).name == launcher.VERIFICATION_FILENAMES[0]


# --------------------------------------------------------------------------- #
# run_codex_verification — success + every error mapping                      #
# --------------------------------------------------------------------------- #

def _run(rid="RID"):
    return launcher.run_codex_verification(rid, _STMT, _PROOF)


def test_run_success_reads_back_payload():
    with _service(_STUB_OK):
        out = _run()
        assert out["verdict"] == "correct"
        assert out["verification_report"]["critical_errors"] == []


def test_run_timeout_504():
    with _service(_STUB_SLOW, timeout="1"):
        try:
            _run()
            assert False, "expected 504"
        except HTTPException as e:
            assert e.status_code == 504 and "timed out" in e.detail


def test_run_nonzero_exit_500():
    with _service(_STUB_FAIL):
        try:
            _run()
            assert False, "expected 500"
        except HTTPException as e:
            assert e.status_code == 500 and "exit code 7" in e.detail


def test_run_missing_output_500():
    with _service(_STUB_NOOUT):
        try:
            _run()
            assert False, "expected 500"
        except HTTPException as e:
            assert e.status_code == 500 and "was not found" in e.detail


def test_run_bad_json_500():
    with _service(_STUB_BADJSON):
        try:
            _run()
            assert False, "expected 500"
        except HTTPException as e:
            assert e.status_code == 500 and "not valid JSON" in e.detail


def test_run_non_dict_json_500():
    with _service(_STUB_NONDICT):
        try:
            _run()
            assert False, "expected 500"
        except HTTPException as e:
            assert e.status_code == 500 and "must be a JSON object" in e.detail


def test_ensure_agent_home_provisions_missing_home():
    # A fresh checkout has no verify agent home; ensure_agent_home builds it
    # (AGENTS.md = verifier contract, .agents/skills = verify skills) so the codex
    # -C dir exists. Regression for the live-found bug: service 500 on a missing home.
    with tempfile.TemporaryDirectory(prefix="verify_home_") as d:
        home = Path(d) / "agent"
        with _env(VERIFY_AGENT_HOME=str(home)):
            got = launcher.ensure_agent_home()
            assert got == home.resolve()
            agents_md = home / "AGENTS.md"
            skills = home / ".agents" / "skills"
            assert agents_md.exists(), "AGENTS.md must be provisioned"
            assert skills.exists(), ".agents/skills must be provisioned"
            # they point at the repo's canonical sources
            assert agents_md.resolve() == (launcher._REPO_ROOT / "agents" / "contracts" / "verifier.md").resolve()
            assert skills.resolve() == (launcher._REPO_ROOT / "agents" / "skills" / "verify").resolve()
            # idempotent: a second call is a no-op and still valid
            launcher.ensure_agent_home()
            assert agents_md.exists() and skills.exists()


def main() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [ok] {name}")
    print("ALL LAUNCHER TESTS PASSED")


if __name__ == "__main__":
    main()
