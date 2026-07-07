"""Offline tests for danus.orchestration — the ``danus`` CLI verbs.

Filesystem verbs (new/assign/status/list) are deterministic. The loop tests are
integration: they spawn the real ``python -m danus.execution`` loop subprocess but
stub codex with a fake shell binary (``DANUS_CODEX_BIN``) so nothing real is
invoked and no API is spent. All processes are force-cleaned in ``finally``.

Runs standalone (``python -m danus.orchestration.tests.test_orchestration``) and
under pytest.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from danus.execution import layout as L
from danus.orchestration import cli


@contextmanager
def _env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def _project_env(tmp: Path, **extra):
    """Agents root + stub worker contract/skills so tests never touch the repo's
    agents/ tree; merge any extra env (codex stub, round vars)."""
    contract = tmp / "worker.md"
    contract.write_text("# worker contract (stub)\n", encoding="utf-8")
    skills = tmp / "skills"
    skills.mkdir(exist_ok=True)
    env = {"DANUS_AGENTS_ROOT": str(tmp / "agents"),
           "DANUS_WORKER_CONTRACT": str(contract),
           "DANUS_WORKER_SKILLS": str(skills)}
    env.update(extra)
    with _env(**env):
        yield


def _fake_codex(d: Path) -> Path:
    """A stub codex: print a round marker, sleep FAKE_CODEX_SLEEP, exit 0."""
    p = d / "fake_codex.sh"
    p.write_text('#!/usr/bin/env bash\necho "fake codex round"\n'
                 'sleep "${FAKE_CODEX_SLEEP:-0}"\nexit 0\n')
    p.chmod(0o755)
    return p


def _wait_until(pred, timeout=15.0, interval=0.05) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


def _st(project: str, worker: str) -> dict:
    return cli.worker_status(L.WorkerLayout(L.worker_dir(project, worker)))


def _kill_project(project: str):
    try:
        cli.do_stop(project, force=True)
    except SystemExit:
        pass
    for d in L.target_worker_dirs(project):
        pid = cli._read_pid(L.WorkerLayout(d))
        if pid:
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass


# --- filesystem verb tests ------------------------------------------------- #

def test_assign_replace_and_rejects(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        cli.do_assign("P/high", "explore direction 3: the symplectic-rank route")
        assert L.WorkerLayout(L.worker_dir("P", "high")).task.read_text() == \
            "explore direction 3: the symplectic-rank route\n"
        cli.do_assign("P/high", "switch to direction 5")   # replace, not append
        assert L.WorkerLayout(L.worker_dir("P", "high")).task.read_text() == "switch to direction 5\n"
        for bad in ["P", "P/nope"]:
            try:
                cli.do_assign(bad, "x")
                assert False, f"should reject {bad!r}"
            except SystemExit:
                pass
        try:
            cli.do_assign("P/high", "   ")
            assert False, "should reject empty task"
        except SystemExit:
            pass


def test_status_before_start(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        s = _st("P", "high")
        assert s["alive"] is False and s["state"] == "created" and s["label"] == "created"


def test_list(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:2", model="gpt-5.5")
        cli.do_new("Q", roles="xhigh:1", model="gpt-x")
        rows = {r["project"]: r for r in cli.do_list()}
        assert rows["P"]["workers"] == 2 and rows["P"]["live"] == 0 and rows["P"]["model"] == "gpt-5.5"
        assert rows["Q"]["workers"] == 1 and rows["Q"]["model"] == "gpt-x"


# --- loop integration tests (stubbed codex) -------------------------------- #

def test_loop_runs_rounds_then_exits(tmp: Path):
    fc = _fake_codex(tmp)
    with _project_env(tmp, DANUS_CODEX_BIN=str(fc), DANUS_ROUND_BEAT="0",
                      DANUS_MAX_ROUNDS="2", FAKE_CODEX_SLEEP="0"):
        cli.do_new("P", roles="high:1")
        try:
            res = cli.do_start("P/high")
            assert res[0]["result"] == "started"
            assert _wait_until(lambda: not _st("P", "high")["alive"]), "loop should exit at backstop"
            s = _st("P", "high")
            assert s["state"] == "max_rounds" and s["round"] == 2
            wl = L.WorkerLayout(L.worker_dir("P", "high"))
            assert (wl.logs / "round_1.log").exists() and (wl.logs / "round_2.log").exists()
        finally:
            _kill_project("P")


def test_graceful_stop(tmp: Path):
    fc = _fake_codex(tmp)
    with _project_env(tmp, DANUS_CODEX_BIN=str(fc), DANUS_ROUND_BEAT="0.1",
                      DANUS_MAX_ROUNDS="0", FAKE_CODEX_SLEEP="0.1"):
        cli.do_new("P", roles="high:1")
        try:
            cli.do_start("P/high")
            assert _wait_until(lambda: _st("P", "high")["round"] >= 1), "should start a round"
            assert _st("P", "high")["alive"] is True
            r = cli.do_stop("P/high")            # graceful
            assert "graceful" in r[0]["result"]
            assert _wait_until(lambda: not _st("P", "high")["alive"]), "loop should exit after .stop"
            assert cli._read_pid(L.WorkerLayout(L.worker_dir("P", "high"))) is None  # pid cleaned
        finally:
            _kill_project("P")


def test_force_stop(tmp: Path):
    fc = _fake_codex(tmp)
    with _project_env(tmp, DANUS_CODEX_BIN=str(fc), DANUS_ROUND_BEAT="0",
                      DANUS_MAX_ROUNDS="0", FAKE_CODEX_SLEEP="30"):
        cli.do_new("P", roles="high:1")
        try:
            cli.do_start("P/high")
            assert _wait_until(lambda: _st("P", "high")["state"] == "running"), "round should run"
            r = cli.do_stop("P/high", force=True)
            assert r[0]["result"] == "killed"
            assert _wait_until(lambda: not _st("P", "high")["alive"], timeout=8), "force kills fast"
        finally:
            _kill_project("P")


def test_idempotent_start(tmp: Path):
    fc = _fake_codex(tmp)
    with _project_env(tmp, DANUS_CODEX_BIN=str(fc), DANUS_ROUND_BEAT="0",
                      DANUS_MAX_ROUNDS="0", FAKE_CODEX_SLEEP="30"):
        cli.do_new("P", roles="high:1")
        try:
            assert cli.do_start("P/high")[0]["result"] == "started"
            assert _wait_until(lambda: _st("P", "high")["alive"])
            assert cli.do_start("P/high")[0]["result"] == "already-running"
        finally:
            _kill_project("P")


def test_project_wide_targets(tmp: Path):
    fc = _fake_codex(tmp)
    with _project_env(tmp, DANUS_CODEX_BIN=str(fc), DANUS_ROUND_BEAT="0",
                      DANUS_MAX_ROUNDS="1", FAKE_CODEX_SLEEP="0"):
        cli.do_new("P", roles="high:2")
        try:
            res = cli.do_start("P")              # whole project
            assert {r["worker"] for r in res} == {"high", "high2"}
            assert _wait_until(lambda: all(not _st("P", w)["alive"] for w in ("high", "high2")))
            assert len(cli.do_status("P")) == 2
        finally:
            _kill_project("P")


def test_missing_codex_returns_error_state(tmp: Path):
    with _project_env(tmp, DANUS_CODEX_BIN="/nonexistent/codex-bin",
                      DANUS_ROUND_BEAT="0", DANUS_MAX_ROUNDS="0"):
        cli.do_new("P", roles="high:1")
        try:
            cli.do_start("P/high")
            # rc 127 => loop must not spin; it errors out immediately
            assert _wait_until(lambda: not _st("P", "high")["alive"]), "loop should exit on missing codex"
            s = _st("P", "high")
            assert s["state"] == "error"
        finally:
            _kill_project("P")


# --- runner ---------------------------------------------------------------- #

def main() -> None:
    fs_tests = [test_assign_replace_and_rejects, test_status_before_start, test_list]
    loop_tests = [test_loop_runs_rounds_then_exits, test_graceful_stop, test_force_stop,
                  test_idempotent_start, test_project_wide_targets,
                  test_missing_codex_returns_error_state]
    for t in fs_tests + loop_tests:
        with tempfile.TemporaryDirectory() as d:
            t(Path(d))
        print(f"  [ok] {t.__name__}")
    print("ALL ORCHESTRATION TESTS PASSED")


if __name__ == "__main__":
    main()
