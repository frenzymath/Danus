"""Offline tests for danus.execution — layout + scaffolding (no codex, no network).

Covers the pure-function layer: role parsing, the typed WorkerLayout, and what
``do_new`` writes (dirs + AGENTS.md/skills symlinks + .codex/config.toml content +
.role/TASK/.status). The loop's stop-condition behavior (which spawns the loop
subprocess against a stubbed codex) is exercised in the orchestration test suite.

Runs standalone (``python -m danus.execution.tests.test_execution``) and pytest.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from danus.execution import layout as L
from danus.execution import loop, scaffold


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
def _project_env(tmp: Path):
    """Point the agents root + worker contract/skills at tmp stubs so the tests
    are self-contained (no dependency on the repo's agents/ tree existing)."""
    contract = tmp / "worker.md"
    contract.write_text("# worker contract (stub)\n", encoding="utf-8")
    skills = tmp / "skills"
    skills.mkdir(exist_ok=True)
    with _env(DANUS_AGENTS_ROOT=str(tmp / "agents"),
              DANUS_WORKER_CONTRACT=str(contract),
              DANUS_WORKER_SKILLS=str(skills)):
        yield


# --- parse_roles ----------------------------------------------------------- #

def test_parse_roles_default_roster():
    pairs = L.parse_roles("high:3,xhigh:4")
    names = [n for n, _ in pairs]
    assert names == ["high", "high2", "high3", "xhigh", "xhigh2", "xhigh3", "xhigh4"]
    # base role (digits stripped) drives reasoning effort
    assert [b for _, b in pairs] == ["high"] * 3 + ["xhigh"] * 4
    assert dict(pairs)["high2"] == "high" and dict(pairs)["xhigh4"] == "xhigh"


def test_parse_roles_rejects_bad_specs():
    for bad in ["", "   ", "high:0", "high", "high:abc", ":3", "3:high"]:
        try:
            L.parse_roles(bad)
            assert False, f"should reject {bad!r}"
        except ValueError:
            pass


# --- WorkerLayout ---------------------------------------------------------- #

def test_worker_layout_paths():
    wl = L.WorkerLayout(Path("/x/proj/workers/high"))
    assert wl.name == "high" and wl.project == "proj"
    assert wl.project_dir == Path("/x/proj")
    assert wl.task.name == L.TASK_FILE and wl.role.name == L.ROLE_FILE
    assert wl.pid.name == L.PID_FILE and wl.lock.name == L.LOCK_FILE
    assert wl.stop.name == L.STOP_FILE and wl.status.name == L.STATUS_FILE
    assert wl.logs.name == L.LOGS_DIR
    assert wl.codex_config == Path("/x/proj/workers/high/.codex/config.toml")


def test_resolve_and_target():
    assert L.resolve_target("proj") == ("proj", None)
    assert L.resolve_target("proj/high") == ("proj", "high")
    assert L.resolve_target("/proj/high/") == ("proj", "high")


# --- do_new scaffolding ---------------------------------------------------- #

def test_do_new_scaffolds_project(tmp: Path):
    with _project_env(tmp):
        r = scaffold.do_new("P", roles="high:2,xhigh:1", model="gpt-5.5")
        assert r["workers"] == ["high", "high2", "xhigh"]
        pdir = L.project_dir("P")
        assert (pdir / "global_memory").is_dir() and (pdir / "fact_graph").is_dir()
        meta = json.loads((pdir / "project.json").read_text())
        assert meta["workers"] == ["high", "high2", "xhigh"] and meta["model"] == "gpt-5.5"

        for w, eff in [("high", "high"), ("high2", "high"), ("xhigh", "xhigh")]:
            wl = L.WorkerLayout(L.worker_dir("P", w))
            assert wl.local_memory.is_dir() and wl.logs.is_dir()
            # symlinks resolve to the (stub) contract + skills
            assert (wl.dir / "AGENTS.md").resolve() == L.worker_md().resolve()
            assert (wl.dir / ".agents" / "skills").resolve() == L.worker_skills_dir().resolve()
            cfg = wl.codex_config.read_text()
            assert 'DANUS_ROLE = "worker"' in cfg
            assert 'args = ["-m", "danus.gateway"]' in cfg  # pinned MCP launch
            assert "tool_timeout_sec = 3600" in cfg
            assert f'DANUS_AUTHOR = "{w}"' in cfg and str(pdir) in cfg
            role = wl.role.read_text()
            assert f"REASONING_EFFORT={eff}" in role and "MODEL=gpt-5.5" in role
            assert "(unassigned" in wl.task.read_text()
            assert json.loads(wl.status.read_text())["state"] == "created"


def test_do_new_refuses_existing(tmp: Path):
    with _project_env(tmp):
        scaffold.do_new("P", roles="high:1")
        try:
            scaffold.do_new("P")
            assert False, "should refuse an existing project dir"
        except SystemExit:
            pass


def test_do_new_verify_url_from_env(tmp: Path):
    with _project_env(tmp):
        with _env(DANUS_VERIFY_URL="http://127.0.0.1:9999/verify"):
            scaffold.do_new("Q", roles="high:1")
        cfg = L.WorkerLayout(L.worker_dir("Q", "high")).codex_config.read_text()
        assert 'DANUS_VERIFY_URL = "http://127.0.0.1:9999/verify"' in cfg


# --- loop helpers (pure) --------------------------------------------------- #

def test_parse_last_fact_id(tmp: Path):
    log = tmp / "round.log"
    log.write_text('noise\nfact_id=0123456789abcdef\nmore\n"fact_id": "fedcba9876543210"\n')
    assert loop._parse_last_fact_id(log) == "fedcba9876543210"
    log.write_text("no facts here, and DEADBEEF is not 16 hex lower\n")
    assert loop._parse_last_fact_id(log) is None


def test_deadline_passed(tmp: Path):
    pdir = tmp / "proj"
    pdir.mkdir()
    assert loop._deadline_passed(pdir) is False           # no deadline file
    (pdir / L.DEADLINE_FILE).write_text("1")              # epoch 1 = long past
    assert loop._deadline_passed(pdir) is True
    (pdir / L.DEADLINE_FILE).write_text("garbage")        # bad = not passed
    assert loop._deadline_passed(pdir) is False


def test_write_status_atomic_and_stamps(tmp: Path):
    wl = L.WorkerLayout(tmp / "proj" / "workers" / "high")
    wl.dir.mkdir(parents=True)
    loop.write_status(wl, state="running", round=2)
    st = json.loads(wl.status.read_text())
    assert st["state"] == "running" and st["round"] == 2
    assert st["worker"] == "high" and st["pid"] == os.getpid() and "updated_at" in st
    # merge, not overwrite: a second write keeps prior fields
    loop.write_status(wl, last_rc=0)
    st2 = json.loads(wl.status.read_text())
    assert st2["round"] == 2 and st2["last_rc"] == 0


def test_read_role_defaults_and_overrides(tmp: Path):
    wl = L.WorkerLayout(tmp / "proj" / "workers" / "xhigh")
    wl.dir.mkdir(parents=True)
    # no .role -> defaults (the neutral DANUS_CODEX_MODEL unset → the built-in
    # gpt-5.5 default)
    with _env(DANUS_CODEX_MODEL=None):
        role = loop._read_role(wl)
    assert role["MODEL"] == "gpt-5.5" and role["ROLE"] == "high" and role["DANUS_AUTHOR"] == "xhigh"
    # the neutral DANUS_CODEX_MODEL is the worker default when .role omits MODEL
    with _env(DANUS_CODEX_MODEL="neutral-model"):
        role = loop._read_role(wl)
    assert role["MODEL"] == "neutral-model"
    wl.role.write_text("# comment\nMODEL=gpt-x\nREASONING_EFFORT=xhigh\n\nROLE=xhigh\n")
    role = loop._read_role(wl)
    assert role["MODEL"] == "gpt-x" and role["REASONING_EFFORT"] == "xhigh" and role["ROLE"] == "xhigh"


# --- runner ---------------------------------------------------------------- #

_NO_TMP = {test_parse_roles_default_roster, test_parse_roles_rejects_bad_specs,
           test_worker_layout_paths, test_resolve_and_target}


def main() -> None:
    for t in [test_parse_roles_default_roster, test_parse_roles_rejects_bad_specs,
              test_worker_layout_paths, test_resolve_and_target,
              test_do_new_scaffolds_project, test_do_new_refuses_existing,
              test_do_new_verify_url_from_env, test_parse_last_fact_id,
              test_deadline_passed, test_write_status_atomic_and_stamps,
              test_read_role_defaults_and_overrides]:
        if t in _NO_TMP:
            t()
        else:
            with tempfile.TemporaryDirectory() as d:
                t(Path(d))
        print(f"  [ok] {t.__name__}")
    print("ALL EXECUTION TESTS PASSED")


if __name__ == "__main__":
    main()
