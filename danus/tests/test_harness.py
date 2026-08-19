"""Offline tests for AgentAdapter: Codex identity, Dsh prompt/runs, call-site gate.

Runs standalone (``python -m danus.tests.test_harness``) and under pytest.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from danus import codex
from danus.execution.loop import kickoff
from danus.harness import CodexAdapter, DshAdapter, get_adapter


@contextlib.contextmanager
def env(**kv):
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


_ALL = dict(CODEX_BACKEND=None)
_REPO = Path(__file__).resolve().parents[2]


def test_get_adapter_defaults_to_codex():
    with env(**_ALL):
        assert isinstance(get_adapter(), CodexAdapter)
    with env(**{**_ALL, "CODEX_BACKEND": "chatgpt"}):
        assert isinstance(get_adapter(), CodexAdapter)
    with env(**{**_ALL, "CODEX_BACKEND": "api"}):
        assert isinstance(get_adapter(), CodexAdapter)


def test_get_adapter_dsh():
    with env(**{**_ALL, "CODEX_BACKEND": "dsh"}):
        assert isinstance(get_adapter(), DshAdapter)


def test_codex_adapter_prepare_prompt_is_identity():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "AGENTS.md"
        p.write_text("CONTRACT", encoding="utf-8")
        out = CodexAdapter().prepare_prompt(
            "solve it", p, tools=("gm_add", "fact_submit"),
        )
        assert out == "solve it"


def test_codex_exec_argv_matches_historical_exec_cmd():
    argv = CodexAdapter().exec_argv("/x/codex", "the-model", "xhigh", "-C", "/home", "-")
    assert argv == [
        "/x/codex", "exec",
        "--model", "the-model",
        "--config", 'model_reasoning_effort="xhigh"',
        "-C", "/home", "-",
    ]


def test_dsh_adapter_embeds_and_maps_tools():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        contract = root / "contract.md"
        contract.write_text("CONTENT-CONTRACT", encoding="utf-8")
        skill = root / "skills" / "a" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("CONTENT-SKILL-A", encoding="utf-8")
        out = DshAdapter().prepare_prompt(
            "solve it", contract, root / "skills",
            tools=("gm_add", "fact_submit"),
        )
        assert out.startswith("solve it")
        assert "CONTENT-CONTRACT" in out
        assert "CONTENT-SKILL-A" in out
        assert "gm_add -> mcp__danus__gm_add" in out
        assert "fact_submit -> mcp__danus__fact_submit" in out
        assert "dsh backend" not in out


def test_dsh_adapter_exec_argv_same_shape_as_codex():
    dsh = DshAdapter().exec_argv("/x/codex-dsh", "m", "e", "prompt")
    cod = CodexAdapter().exec_argv("/x/codex-dsh", "m", "e", "prompt")
    assert dsh == cod


def test_verify_results_root_codex_vs_dsh():
    home = Path("/tmp/agent-home")
    pkg = Path("/tmp/package/runs")
    assert CodexAdapter().verify_results_root(
        agent_home=home, package_runs=pkg,
    ) == pkg.resolve()
    assert DshAdapter().verify_results_root(
        agent_home=home, package_runs=pkg,
    ) == (home / "runs").resolve()


def test_facade_prepare_prompt_follows_backend():
    with tempfile.TemporaryDirectory() as td:
        contract = Path(td) / "c.md"
        contract.write_text("BODY", encoding="utf-8")
        with env(**_ALL):
            assert codex.prepare_prompt("p", contract, tools=("gm_add",)) == "p"
        with env(**{**_ALL, "CODEX_BACKEND": "dsh"}):
            out = codex.prepare_prompt("p", contract, tools=("gm_add",))
            assert "BODY" in out
            assert "gm_add -> mcp__danus__gm_add" in out


def test_call_sites_do_not_branch_on_dsh():
    for rel in (
        "danus/execution/loop.py",
        "danus/verify/launcher.py",
        "danus/authoring/driver.py",
    ):
        text = (_REPO / rel).read_text(encoding="utf-8")
        assert 'backend() == "dsh"' not in text, rel
        assert "backend() == 'dsh'" not in text, rel


def test_kickoff_tool_footnote_only_on_dsh():
    with env(**_ALL):
        p = kickoff("ProjX", "wkrY")
        assert "wkrY" in p and "ProjX" in p
        assert "mcp__danus" not in p
    with env(**{**_ALL, "CODEX_BACKEND": "dsh"}):
        p = kickoff("ProjX", "wkrY")
        assert "gm_add -> mcp__danus__gm_add" in p
        assert "dsh backend" not in p


def test_repo_has_no_dsh_web_mcp_registration():
    for rel in (
        "scripts/apply-dsh-mcp.sh",
        "scripts/dsh_mcp_probe.py",
        "examples/dsh-integration/cordis.patch.yml.example",
    ):
        assert not (_REPO / rel).exists(), rel


def main() -> None:
    tests = [
        test_get_adapter_defaults_to_codex,
        test_get_adapter_dsh,
        test_codex_adapter_prepare_prompt_is_identity,
        test_codex_exec_argv_matches_historical_exec_cmd,
        test_dsh_adapter_embeds_and_maps_tools,
        test_dsh_adapter_exec_argv_same_shape_as_codex,
        test_verify_results_root_codex_vs_dsh,
        test_facade_prepare_prompt_follows_backend,
        test_call_sites_do_not_branch_on_dsh,
        test_kickoff_tool_footnote_only_on_dsh,
        test_repo_has_no_dsh_web_mcp_registration,
    ]
    for t in tests:
        t()
        print(f"  [ok] {t.__name__}")
    print("ALL HARNESS TESTS PASSED")


if __name__ == "__main__":
    main()
