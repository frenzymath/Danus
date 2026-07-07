"""Offline, fully-mocked coverage of every ``danus`` CLI verb + helper.

Unlike ``test_orchestration.py`` (which spawns the real loop subprocess with a
stub codex), this module never launches *any* process: ``spawn_loop`` is
monkeypatched to a recording fake, so ``do_start`` / ``main start`` exercise the
flock + pid bookkeeping without a fork. Everything runs under a tempdir agents
root. Targets the read helpers, the error/edge paths of each verb, the two text
formatters, the ``_task_from_args`` source selection, ``build_parser``, and the
full ``main`` dispatch table — plus ``python -m danus.orchestration`` via runpy.

Runs standalone (``python -m danus.orchestration.tests.test_cli_verbs``) and
under pytest.
"""

from __future__ import annotations

import io
import json
import os
import runpy
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

from danus.execution import layout as L
from danus.orchestration import cli


# --------------------------------------------------------------------------- #
# env / project helpers (mirrors test_orchestration.py so styles match)        #
# --------------------------------------------------------------------------- #

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


class _FakeSpawn:
    """Records (wdir) calls; returns our *own* pid so ``_alive`` reports True and
    ``_start_one`` treats the worker as live — without launching anything."""

    def __init__(self):
        self.calls = []

    def __call__(self, wdir):
        self.calls.append(Path(wdir))
        return os.getpid()


@contextmanager
def _patch_spawn():
    fake = _FakeSpawn()
    orig = cli.spawn_loop
    cli.spawn_loop = fake
    try:
        yield fake
    finally:
        cli.spawn_loop = orig


def _wl(project: str, worker: str) -> L.WorkerLayout:
    return L.WorkerLayout(L.worker_dir(project, worker))


def _expect_exit(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except SystemExit as e:
        return e
    raise AssertionError(f"expected SystemExit from {getattr(fn, '__name__', fn)}")


# --------------------------------------------------------------------------- #
# read helpers: _read_pid / _alive / _read_status                              #
# --------------------------------------------------------------------------- #

def test_read_pid_missing_and_garbage(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        assert cli._read_pid(wl) is None            # no .pid yet
        wl.pid.write_text("not-an-int\n")
        assert cli._read_pid(wl) is None            # ValueError -> None
        wl.pid.write_text("4321\n")
        assert cli._read_pid(wl) == 4321


def test_alive_variants(tmp: Path):
    # falsy pid / None -> dead
    assert cli._alive(None) is False
    assert cli._alive(0) is False
    # our own process is alive (and not a zombie)
    assert cli._alive(os.getpid()) is True
    # a pid that (almost certainly) does not exist -> ProcessLookupError -> dead
    assert cli._alive(2_000_000_000) is False


def test_stop_one_force_sigkill_fallback(tmp: Path):
    """A child that ignores SIGTERM must be finished by the SIGKILL fallback
    (cli.py lines 245-248). We launch a real python child that traps SIGTERM into
    a no-op, signals readiness via a file, then sleeps; force-stop should SIGTERM
    (ignored), wait ~5s, then SIGKILL. Real process we own — never codex.

    Waiting for the readiness file is essential: if we stop before the SIGTERM
    handler is installed, the default handler kills the child immediately and the
    SIGKILL branch is never reached."""
    import subprocess
    import sys
    import time
    ready = tmp / "handler_ready"
    prog = (
        "import signal, time, sys\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(ready)!r}, 'w').close()\n"
        "time.sleep(120)\n"
    )
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        proc = subprocess.Popen([sys.executable, "-c", prog], start_new_session=True)
        wl.pid.write_text(str(proc.pid))
        try:
            # wait until the child has installed its SIGTERM-ignoring handler
            end = time.time() + 10
            while time.time() < end and not ready.exists():
                time.sleep(0.02)
            assert ready.exists(), "child never signalled readiness"
            assert cli._alive(proc.pid) is True
            t0 = time.time()
            res = cli._stop_one(wl, force=True)       # SIGTERM ignored -> SIGKILL fallback
            assert res == "killed"
            assert time.time() - t0 >= 4.5, "should have waited the full SIGTERM grace"
            # confirm it's really gone
            end = time.time() + 5
            while time.time() < end and cli._alive(proc.pid):
                time.sleep(0.05)
            assert cli._alive(proc.pid) is False
            assert not wl.pid.exists()
        finally:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass


def test_stop_one_force_sigkill_killpg_raises(tmp: Path):
    """Defensive branch (cli.py 247-248): the final SIGKILL ``os.killpg`` itself
    raises ProcessLookupError (the process died in the tiny window between the last
    ``_alive`` check and the kill). It must be swallowed and still return 'killed'.
    Fully stubbed — ``_alive`` is forced True through the wait loop, ``os.getpgid``
    is a no-op, and ``os.killpg`` raises; no real process is touched."""
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        wl.pid.write_text("2000000000")

        real_alive = cli._alive
        real_getpgid = cli.os.getpgid
        real_killpg = cli.os.killpg
        real_sleep = cli.time.sleep

        cli._alive = lambda pid: True                 # always "alive" -> reaches SIGKILL
        cli.os.getpgid = lambda pid: 12345
        def boom_killpg(pgid, sig):
            raise ProcessLookupError("gone before SIGKILL")
        cli.os.killpg = boom_killpg
        cli.time.sleep = lambda s: None               # don't actually wait ~5s
        try:
            assert cli._stop_one(wl, force=True) == "killed"
            assert not wl.pid.exists()
        finally:
            cli._alive = real_alive
            cli.os.getpgid = real_getpgid
            cli.os.killpg = real_killpg
            cli.time.sleep = real_sleep


def test_alive_proc_read_failure_defaults_alive(tmp: Path):
    """Race branch (cli.py 70-71): ``os.kill(pid,0)`` succeeds (pid exists) but the
    ``/proc/<pid>/stat`` read fails (the process vanished between the two calls, or
    /proc is unavailable). ``_alive`` conservatively returns True. We simulate the
    race by patching ``cli.Path`` so the /proc read raises OSError, using our own
    (definitely-live, non-zombie) pid so os.kill succeeds."""
    real_Path = cli.Path

    class _BoomPath:
        def __init__(self, *a, **k):
            pass
        def read_text(self, *a, **k):
            raise OSError("simulated /proc read failure")

    cli.Path = _BoomPath
    try:
        assert cli._alive(os.getpid()) is True        # kill ok, /proc read boom -> True
    finally:
        cli.Path = real_Path


def test_stop_one_force_getpgid_raises(tmp: Path):
    """Force path where ``os.getpgid`` raises (cli.py 238-239): the process is seen
    alive by ``_alive`` but disappears before ``getpgid`` — the ProcessLookupError
    is swallowed, then the wait loop finds it dead and returns 'killed'. We stub
    ``cli.os.getpgid`` to raise and use a dead pid for the subsequent _alive checks
    so the loop exits at once."""
    import types
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")

        real_getpgid = cli.os.getpgid
        real_alive = cli._alive
        # first _alive (guard) True, then getpgid raises, then loop sees dead
        state = {"n": 0}

        def fake_alive(pid):
            state["n"] += 1
            return state["n"] == 1                     # alive once (the guard), dead after

        def boom_getpgid(pid):
            raise ProcessLookupError("gone between alive and getpgid")

        wl.pid.write_text("2000000000")
        cli.os.getpgid = boom_getpgid
        cli._alive = fake_alive
        try:
            assert cli._stop_one(wl, force=True) == "killed"
            assert not wl.pid.exists()
        finally:
            cli.os.getpgid = real_getpgid
            cli._alive = real_alive


def test_read_status_missing_and_bad_json(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        # do_new wrote a valid status; corrupt it -> {}
        wl.status.write_text("{ not json", encoding="utf-8")
        assert cli._read_status(wl) == {}
        # remove it -> {}
        wl.status.unlink()
        assert cli._read_status(wl) == {}


def test_alive_permission_error_means_alive():
    """A pid we can't signal (owned by another user, e.g. init pid 1) raises
    PermissionError from ``os.kill(pid, 0)`` -> treated as alive ('exists but not
    ours'). pid 1 always exists and is root-owned when we're not root."""
    if os.geteuid() == 0:
        return  # as root os.kill(1,0) succeeds; the PermissionError branch is unreachable
    assert cli._alive(1) is True


def test_alive_zombie_is_dead():
    """A child that exited but hasn't been reaped is a zombie; /proc reports state
    'Z' and ``_alive`` must call it dead. We fork a child that exits immediately
    and do NOT wait() it, so it lingers as a zombie we own."""
    import subprocess
    import time
    # 'true' exits at once; without wait() it becomes a zombie child of us.
    proc = subprocess.Popen(["true"])
    try:
        # wait for the kernel to mark it Z (exited, unreaped)
        pid = proc.pid
        def is_zombie():
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
                return stat.rsplit(")", 1)[1].split()[0] == "Z"
            except (OSError, IndexError):
                return False
        end = time.time() + 5
        while time.time() < end and not is_zombie():
            time.sleep(0.02)
        assert is_zombie(), "child did not become a zombie"
        assert cli._alive(pid) is False              # /proc state 'Z' => dead
    finally:
        proc.wait()                                   # reap it


# --------------------------------------------------------------------------- #
# worker_status labels                                                          #
# --------------------------------------------------------------------------- #

def test_worker_status_stuck_label(tmp: Path):
    """alive + state=running + round_started_at far in the past -> 'stuck?'."""
    with _project_env(tmp, DANUS_ROUND_HARD_TIMEOUT="10"):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        wl.pid.write_text(str(os.getpid()))          # our pid => alive
        old = 1.0                                     # epoch ~1970 => hugely stale
        wl.status.write_text(json.dumps(
            {"state": "running", "round": 5, "round_started_at": old,
             "last_round_at": old, "last_fact_id": "F9"}))
        s = cli.worker_status(wl)
        assert s["alive"] is True and s["label"] == "stuck?"
        assert s["age_s"] is not None and s["last_fact_id"] == "F9"


def test_worker_status_working_and_dead_labels(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        # alive + running but fresh => 'working'
        import time
        wl.pid.write_text(str(os.getpid()))
        wl.status.write_text(json.dumps(
            {"state": "running", "round": 2, "round_started_at": time.time()}))
        assert cli.worker_status(wl)["label"] == "working"
        # not alive + unknown terminal state => 'dead'
        wl.pid.write_text("2000000000")
        wl.status.write_text(json.dumps({"state": "weird", "round": 3}))
        d = cli.worker_status(wl)
        assert d["alive"] is False and d["label"] == "dead" and d["age_s"] is None
        # not alive + recognized terminal state => that state as label
        wl.status.write_text(json.dumps({"state": "deadline", "round": 3}))
        assert cli.worker_status(wl)["label"] == "deadline"


# --------------------------------------------------------------------------- #
# do_start: mocked spawn, locked path, no-workers, project-wide + stagger       #
# --------------------------------------------------------------------------- #

def test_do_start_calls_spawn_with_worker_dir(tmp: Path):
    with _project_env(tmp), _patch_spawn() as fake:
        cli.do_new("P", roles="high:1")
        res = cli.do_start("P/high")
        assert res == [{"worker": "high", "result": "started"}]
        assert fake.calls == [_wl("P", "high").dir]
        wl = _wl("P", "high")
        assert cli._read_pid(wl) == os.getpid()      # pid file written from fake pid
        # second start sees our-own-pid as alive => idempotent already-running
        res2 = cli.do_start("P/high")
        assert res2 == [{"worker": "high", "result": "already-running"}]
        assert len(fake.calls) == 1                   # spawn NOT called again


def test_do_start_locked_returns_locked(tmp: Path):
    import fcntl
    with _project_env(tmp), _patch_spawn():
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        wl.dir.mkdir(parents=True, exist_ok=True)
        held = open(wl.lock, "w")
        fcntl.flock(held, fcntl.LOCK_EX)
        try:
            assert cli._start_one(wl) == "locked"
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
            held.close()


def test_do_start_clears_stale_stop(tmp: Path):
    with _project_env(tmp), _patch_spawn():
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        wl.dir.mkdir(parents=True, exist_ok=True)
        wl.stop.touch()
        assert cli._start_one(wl) == "started"
        assert not wl.stop.exists()                   # stale stop cleared


def test_do_start_no_workers_raises(tmp: Path):
    with _project_env(tmp), _patch_spawn():
        e = _expect_exit(cli.do_start, "ghost")
        assert "no workers for target" in str(e)


def test_do_start_project_wide_stagger(tmp: Path):
    with _project_env(tmp), _patch_spawn() as fake:
        cli.do_new("P", roles="high:2")
        res = cli.do_start("P", stagger=0)            # stagger 0 => no sleep
        assert {r["worker"] for r in res} == {"high", "high2"}
        assert {r["result"] for r in res} == {"started"}
        assert {c.name for c in fake.calls} == {"high", "high2"}


# --------------------------------------------------------------------------- #
# do_status / do_stop no-workers                                                #
# --------------------------------------------------------------------------- #

def test_do_status_no_workers_raises(tmp: Path):
    with _project_env(tmp):
        assert "no workers" in str(_expect_exit(cli.do_status, "ghost"))


def test_do_stop_no_workers_raises(tmp: Path):
    with _project_env(tmp):
        assert "no workers" in str(_expect_exit(cli.do_stop, "ghost"))


# --------------------------------------------------------------------------- #
# _stop_one: not-running (graceful + force), graceful touch, force kill path     #
# --------------------------------------------------------------------------- #

def test_stop_one_not_running_graceful(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        assert cli._stop_one(wl, force=False) == "not-running"


def test_stop_one_not_running_force_cleans_pid(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        wl.pid.write_text("2000000000")               # dead pid
        assert cli._stop_one(wl, force=True) == "not-running"
        assert not wl.pid.exists()                     # stale pid removed


def test_stop_one_graceful_touches_stop(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        wl.pid.write_text(str(os.getpid()))            # alive (our pid)
        assert cli._stop_one(wl, force=False) == "stopping (graceful)"
        assert wl.stop.exists()
        wl.stop.unlink()                               # don't leave a stop flag on us


def test_stop_one_force_kills_a_real_child(tmp: Path):
    """Spawn a genuine harmless child (sleep), record its pid, force-stop it, and
    assert it's reaped as 'killed'. This is a real process we own — safe to kill,
    never a codex/worker (which the RULES forbid launching)."""
    import subprocess
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        wl = _wl("P", "high")
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        wl.pid.write_text(str(proc.pid))
        try:
            assert cli._stop_one(wl, force=True) == "killed"
            assert not wl.pid.exists()
        finally:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# do_finalize: validate + write / reject unknown / suggestion mode             #
# --------------------------------------------------------------------------- #

def _add_fact(project: str, statement: str = "S", proof: str = "P", preds=None) -> str:
    """Add a verified fact to a project's fact graph (test helper — writes via the
    core FactGraph, the same path fact_submit uses on accept)."""
    from danus.core import FactGraph
    fg = FactGraph(L.project_dir(project))
    return fg.add(problem_id="p", author="a", statement=statement, proof=proof,
                  predecessors=preds or [])


def test_finalize_validates_and_writes(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        fid = _add_fact("P")
        r = cli.do_finalize("P", [fid])
        assert r["target_fact_ids"] == [fid]
        target = L.project_dir("P") / "TARGET.md"
        assert target.exists() and fid in target.read_text(encoding="utf-8")
        # write-paper's reader sees the same id
        from danus.write_paper import assemble
        assert assemble.target_fact_ids(L.project_dir("P")) == [fid]


def test_finalize_dedups_preserving_order(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        f1 = _add_fact("P", statement="one")
        f2 = _add_fact("P", statement="two")
        r = cli.do_finalize("P", [f1, f2, f1])
        assert r["target_fact_ids"] == [f1, f2]


def test_finalize_rejects_unknown_fact_id(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        e = _expect_exit(cli.do_finalize, "P", ["fact_does_not_exist"])
        assert "unknown fact id" in str(e)
        # nothing written
        assert not (L.project_dir("P") / "TARGET.md").exists()


def test_finalize_rejects_unknown_project(tmp: Path):
    with _project_env(tmp):
        assert "no such project" in str(_expect_exit(cli.do_finalize, "ghost", ["x"]))


def test_finalize_suggestion_mode_writes_nothing(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        leaf = _add_fact("P", statement="leaf")
        top = _add_fact("P", statement="top", preds=[leaf])   # leaf is a predecessor
        r = cli.do_finalize("P", [])                          # suggestion mode
        assert "suggested" in r
        assert r["suggested"] == [top], "only the terminal fact is suggested"
        assert leaf not in r["suggested"]
        assert not (L.project_dir("P") / "TARGET.md").exists(), "suggestion writes nothing"


def test_main_finalize_write_and_suggest(tmp: Path):
    with _project_env(tmp), _patch_spawn():
        _run_main(["new", "P", "--roles", "high:1"])
        fid = _add_fact("P")
        rc, out = _run_main(["finalize", "P", fid])
        assert rc == 0 and "finalized target for P" in out and fid in out
        # suggestion mode via main (blank fact_ids)
        rc, out = _run_main(["finalize", "P"])
        assert rc == 0 and ("candidate target facts" in out or "no candidate" in out)


# --------------------------------------------------------------------------- #
# do_list: bad project.json, formatting                                         #
# --------------------------------------------------------------------------- #

def test_do_list_bad_project_json(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1", model="gpt-5.5")
        (L.project_dir("P") / "project.json").write_text("{ broken", encoding="utf-8")
        rows = {r["project"]: r for r in cli.do_list()}
        assert rows["P"]["model"] == "—"               # unparseable meta => dash


def test_do_list_missing_project_json(tmp: Path):
    with _project_env(tmp):
        cli.do_new("P", roles="high:1")
        (L.project_dir("P") / "project.json").unlink()
        rows = {r["project"]: r for r in cli.do_list()}
        assert rows["P"]["model"] == "—"


# --------------------------------------------------------------------------- #
# text formatters _fmt_list / _fmt_status                                       #
# --------------------------------------------------------------------------- #

def test_fmt_list_empty_and_rows():
    assert cli._fmt_list([]) == "(no projects under the agents root)"
    rows = [{"project": "Proj", "workers": 3, "live": 1, "model": "gpt-5.5"}]
    out = cli._fmt_list(rows)
    assert "PROJECT" in out and "Proj" in out and "gpt-5.5" in out


def test_fmt_status_rows():
    rows = [
        {"worker": "high", "label": "working", "state": "running", "round": 4,
         "age_s": 12.4, "last_fact_id": "F7"},
        {"worker": "xhigh", "label": "dead", "state": "created", "round": 0,
         "age_s": None, "last_fact_id": None},
    ]
    out = cli._fmt_status(rows)
    assert "WORKER" in out and "high" in out and "xhigh" in out
    assert "12s" in out                                # age rendered from float
    assert "—" in out                                  # None age / fact => dash


# --------------------------------------------------------------------------- #
# _task_from_args: --task / --file / --stdin / none                             #
# --------------------------------------------------------------------------- #

class _Args:
    def __init__(self, task=None, file=None, stdin=False):
        self.task = task
        self.file = file
        self.stdin = stdin


def test_task_from_args_task():
    assert cli._task_from_args(_Args(task="direct task")) == "direct task"


def test_task_from_args_file(tmp: Path):
    p = tmp / "task.txt"
    p.write_text("from a file\n", encoding="utf-8")
    assert cli._task_from_args(_Args(file=str(p))) == "from a file\n"


def test_task_from_args_stdin(monkeypatch=None):
    import sys
    old = sys.stdin
    sys.stdin = io.StringIO("piped task\n")
    try:
        assert cli._task_from_args(_Args(stdin=True)) == "piped task\n"
    finally:
        sys.stdin = old


def test_task_from_args_none_raises():
    assert "one of --task" in str(_expect_exit(cli._task_from_args, _Args()))


# --------------------------------------------------------------------------- #
# build_parser                                                                  #
# --------------------------------------------------------------------------- #

def test_build_parser_all_verbs():
    p = cli.build_parser()
    assert p.parse_args(["list", "--json"]).cmd == "list"
    a = p.parse_args(["new", "P", "--roles", "high:2", "--model", "m"])
    assert a.cmd == "new" and a.project == "P" and a.roles == "high:2" and a.model == "m"
    a = p.parse_args(["assign", "P/high", "--task", "t"])
    assert a.cmd == "assign" and a.target == "P/high" and a.task == "t"
    a = p.parse_args(["finalize", "P", "fact_a", "fact_b"])
    assert a.cmd == "finalize" and a.project == "P" and a.fact_ids == ["fact_a", "fact_b"]
    assert p.parse_args(["finalize", "P"]).fact_ids == []      # suggestion mode
    assert p.parse_args(["start", "P"]).cmd == "start"
    assert p.parse_args(["status", "P", "--json"]).json is True
    assert p.parse_args(["stop", "P", "--force"]).force is True
    # subcommand is required
    try:
        p.parse_args([])
        raise AssertionError("expected argparse to require a subcommand")
    except SystemExit:
        pass


# --------------------------------------------------------------------------- #
# main dispatch — every verb, text + json branches                             #
# --------------------------------------------------------------------------- #

def _run_main(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


def test_main_new_then_list_text_and_json(tmp: Path):
    with _project_env(tmp), _patch_spawn():
        rc, out = _run_main(["new", "P", "--roles", "high:2", "--model", "gpt-5.5"])
        assert rc == 0 and "created P with 2 workers" in out and "high" in out
        rc, out = _run_main(["list"])
        assert rc == 0 and "PROJECT" in out and "P" in out
        rc, out = _run_main(["list", "--json"])
        rows = json.loads(out)
        assert rc == 0 and rows[0]["project"] == "P" and rows[0]["workers"] == 2


def test_main_assign(tmp: Path):
    with _project_env(tmp), _patch_spawn():
        _run_main(["new", "P", "--roles", "high:1"])
        rc, out = _run_main(["assign", "P/high", "--task", "prove lemma 4"])
        assert rc == 0 and "assigned P/high" in out
        assert _wl("P", "high").task.read_text() == "prove lemma 4\n"


def test_main_start_status_stop(tmp: Path):
    with _project_env(tmp), _patch_spawn() as fake:
        _run_main(["new", "P", "--roles", "high:1"])
        rc, out = _run_main(["start", "P/high"])
        assert rc == 0 and "high: started" in out and len(fake.calls) == 1
        # status text branch (worker is "alive" = our pid)
        rc, out = _run_main(["status", "P/high"])
        assert rc == 0 and "WORKER" in out
        # status json branch
        rc, out = _run_main(["status", "P/high", "--json"])
        assert rc == 0 and json.loads(out)[0]["worker"] == "high"
        # stop graceful (worker "alive" via our pid => touches .stop)
        rc, out = _run_main(["stop", "P/high"])
        assert rc == 0 and "graceful" in out
        _wl("P", "high").stop.unlink(missing_ok=True)


def test_main_stop_force_not_running(tmp: Path):
    with _project_env(tmp), _patch_spawn():
        _run_main(["new", "P", "--roles", "high:1"])
        rc, out = _run_main(["stop", "P/high", "--force"])
        assert rc == 0 and "not-running" in out


# --------------------------------------------------------------------------- #
# python -m danus.orchestration  (the __main__ entry point)                     #
# --------------------------------------------------------------------------- #

def test_dunder_main_entrypoint(tmp: Path):
    """Exercise ``__main__.py`` via runpy with a mocked ``main`` so no real verb
    runs. Asserts it calls ``sys.exit`` with main()'s return code."""
    import danus.orchestration.cli as climod

    orig = climod.main
    calls = {}

    def fake_main(argv=None):
        calls["argv"] = argv
        return 0

    climod.main = fake_main
    old_argv = None
    try:
        import sys
        old_argv = sys.argv[:]
        sys.argv = ["danus", "list"]
        try:
            runpy.run_module("danus.orchestration", run_name="__main__")
            raise AssertionError("expected SystemExit from __main__")
        except SystemExit as e:
            assert e.code == 0
    finally:
        climod.main = orig
        if old_argv is not None:
            import sys
            sys.argv = old_argv


# --------------------------------------------------------------------------- #
# runner (standalone parity with test_orchestration.py)                         #
# --------------------------------------------------------------------------- #

def main() -> None:
    no_arg = [
        test_fmt_list_empty_and_rows, test_fmt_status_rows,
        test_task_from_args_task, test_task_from_args_stdin,
        test_task_from_args_none_raises, test_build_parser_all_verbs,
        test_alive_permission_error_means_alive, test_alive_zombie_is_dead,
    ]
    tmp_tests = [
        test_alive_variants,
        test_stop_one_force_sigkill_fallback,
        test_stop_one_force_sigkill_killpg_raises,
        test_alive_proc_read_failure_defaults_alive,
        test_stop_one_force_getpgid_raises,
        test_read_pid_missing_and_garbage, test_read_status_missing_and_bad_json,
        test_worker_status_stuck_label, test_worker_status_working_and_dead_labels,
        test_do_start_calls_spawn_with_worker_dir, test_do_start_locked_returns_locked,
        test_do_start_clears_stale_stop, test_do_start_no_workers_raises,
        test_do_start_project_wide_stagger, test_do_status_no_workers_raises,
        test_do_stop_no_workers_raises, test_stop_one_not_running_graceful,
        test_stop_one_not_running_force_cleans_pid, test_stop_one_graceful_touches_stop,
        test_stop_one_force_kills_a_real_child, test_do_list_bad_project_json,
        test_do_list_missing_project_json, test_task_from_args_file,
        test_finalize_validates_and_writes, test_finalize_dedups_preserving_order,
        test_finalize_rejects_unknown_fact_id, test_finalize_rejects_unknown_project,
        test_finalize_suggestion_mode_writes_nothing, test_main_finalize_write_and_suggest,
        test_main_new_then_list_text_and_json, test_main_assign,
        test_main_start_status_stop, test_main_stop_force_not_running,
        test_dunder_main_entrypoint,
    ]
    for t in no_arg:
        t()
        print(f"  [ok] {t.__name__}")
    for t in tmp_tests:
        with tempfile.TemporaryDirectory() as d:
            t(Path(d))
        print(f"  [ok] {t.__name__}")
    print("ALL CLI VERB TESTS PASSED")


if __name__ == "__main__":
    main()
