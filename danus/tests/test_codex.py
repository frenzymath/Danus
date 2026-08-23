"""Offline tests for danus.codex — the single shared codex launcher.

Covers the four uniform pieces: binary resolution precedence (DANUS_CODEX_BIN
legacy alias, the <repo>/bin/codex wrapper, and shutil.which), model/effort
precedence (per-service overrides -> neutral DANUS_CODEX_* -> built-in default,
override names), subprocess_env (prepend the binary DIR to PATH only for a
concrete path; never inject the CWD for the bare "codex" fallback), and the
exec_cmd shape (quoted model_reasoning_effort + verbatim tail).

Zero network / API spend. Runs standalone
(``python -m danus.tests.test_codex``) and under pytest.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

from danus import codex


@contextlib.contextmanager
def env(**kv):
    """Temporarily set env vars (None deletes), restore after."""
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


# All env names the launcher consults — cleared as the baseline so ambient config
# never leaks into a precedence assertion.
_ALL = dict(
    DANUS_CODEX_BIN=None, CODEX_BIN=None,
    DANUS_MAIN_MODEL=None, DANUS_MAIN_EFFORT=None,
    DANUS_CODEX_MODEL=None, DANUS_CODEX_EFFORT=None,
    DANUS_WORKER_MODEL=None,
    DANUS_VERIFY_MODEL=None, DANUS_VERIFY_EFFORT=None,
    DANUS_WRITE_PAPER_MODEL=None, DANUS_WRITE_PAPER_EFFORT=None,
    DANUS_HUMAN_SUMMARY_MODEL=None, DANUS_HUMAN_SUMMARY_EFFORT=None,
)


# --- resolve_bin precedence ------------------------------------------------- #

def test_resolve_bin_prefers_danus_codex_bin_over_alias():
    with env(**{**_ALL, "DANUS_CODEX_BIN": "/x/primary", "CODEX_BIN": "/x/alias"}):
        assert codex.resolve_bin() == "/x/primary"


def test_resolve_bin_falls_back_to_wrapper_then_which_then_bare():
    # no env override → the <repo>/bin/codex wrapper wins if it exists, else
    # shutil.which("codex"), else the bare string "codex".
    with env(**_ALL):
        got = codex.resolve_bin()
        import shutil
        wrapper = Path(codex.__file__).resolve().parents[1] / "bin" / "codex"
        if wrapper.exists():
            assert got == str(wrapper)
        else:
            assert got == (shutil.which("codex") or "codex")


def test_resolve_bin_bare_when_nothing_available(monkeypatch=None):
    # simulate: no env, no wrapper, no codex on PATH → bare "codex"
    import shutil
    real_which = shutil.which
    shutil.which = lambda *a, **k: None  # type: ignore[assignment]
    try:
        with env(**_ALL):
            # if the repo happens to ship a bin/codex wrapper, that legitimately
            # wins; only assert the bare-string fallback when no wrapper exists.
            wrapper = Path(codex.__file__).resolve().parents[1] / "bin" / "codex"
            if not wrapper.exists():
                assert codex.resolve_bin() == "codex"
    finally:
        shutil.which = real_which  # type: ignore[assignment]


# --- model / effort precedence ---------------------------------------------- #

def test_model_override_wins_then_neutral_then_default():
    with env(**{**_ALL, "DANUS_VERIFY_MODEL": "override-m", "DANUS_CODEX_MODEL": "neutral-m"}):
        assert codex.model("DANUS_VERIFY_MODEL") == "override-m"
    with env(**{**_ALL, "DANUS_CODEX_MODEL": "neutral-m"}):
        assert codex.model("DANUS_VERIFY_MODEL") == "neutral-m"
    with env(**_ALL):
        assert codex.model("DANUS_VERIFY_MODEL") == codex.DEFAULT_MODEL == "gpt-5.6-sol"


def test_model_main_wins_over_codex_alias():
    # DANUS_MAIN_MODEL is the primary neutral name; DANUS_CODEX_MODEL is the
    # back-compat alias used only when DANUS_MAIN_MODEL is unset.
    with env(**{**_ALL, "DANUS_MAIN_MODEL": "main-m", "DANUS_CODEX_MODEL": "legacy-m"}):
        assert codex.model() == "main-m"
    with env(**{**_ALL, "DANUS_CODEX_MODEL": "legacy-m"}):
        assert codex.model() == "legacy-m"


def test_effort_override_wins_then_neutral_then_default():
    with env(**{**_ALL, "DANUS_VERIFY_EFFORT": "override-e", "DANUS_CODEX_EFFORT": "neutral-e"}):
        assert codex.effort("DANUS_VERIFY_EFFORT") == "override-e"
    with env(**{**_ALL, "DANUS_CODEX_EFFORT": "neutral-e"}):
        assert codex.effort("DANUS_VERIFY_EFFORT") == "neutral-e"
    with env(**_ALL):
        assert codex.effort("DANUS_VERIFY_EFFORT") == codex.DEFAULT_EFFORT == "xhigh"


def test_first_override_in_order_wins():
    with env(**{**_ALL, "DANUS_VERIFY_MODEL": "primary", "DANUS_WRITE_PAPER_MODEL": "other"}):
        # the first listed override name wins
        assert codex.model("DANUS_VERIFY_MODEL", "DANUS_WRITE_PAPER_MODEL") == "primary"


# --- subprocess_env --------------------------------------------------------- #

def test_subprocess_env_prepends_dir_for_concrete_path():
    with env(**{**_ALL, "PATH": "/usr/bin:/bin"}):
        out = codex.subprocess_env("/opt/codex/bin/codex")
        assert out["PATH"].split(os.pathsep)[0] == "/opt/codex/bin"
        assert "/usr/bin" in out["PATH"]


def test_subprocess_env_never_injects_cwd_for_bare_codex():
    with env(**{**_ALL, "PATH": "/usr/bin:/bin"}):
        out = codex.subprocess_env("codex")
        # the bare-name fallback has no dir component → PATH is untouched, and the
        # CWD ("" / ".") is NOT injected.
        assert out["PATH"] == "/usr/bin:/bin"
        assert "" not in out["PATH"].split(os.pathsep)
        assert "." not in out["PATH"].split(os.pathsep)


def test_subprocess_env_idempotent_when_dir_already_on_path():
    with env(**{**_ALL, "PATH": "/opt/codex/bin:/usr/bin"}):
        out = codex.subprocess_env("/opt/codex/bin/codex")
        # already present → not duplicated
        assert out["PATH"] == "/opt/codex/bin:/usr/bin"


# --- exec_cmd shape --------------------------------------------------------- #

def test_exec_cmd_shape_quoted_effort_and_verbatim_tail():
    cmd = codex.exec_cmd("/x/codex", "the-model", "xhigh", "-C", "/home", "-")
    assert cmd == [
        "/x/codex", "exec",
        "--model", "the-model",
        "--config", 'model_reasoning_effort="xhigh"',
        "-C", "/home", "-",
    ]


def test_exec_cmd_empty_tail():
    cmd = codex.exec_cmd("codex", "m", "e")
    assert cmd == ["codex", "exec", "--model", "m", "--config", 'model_reasoning_effort="e"']


# --- per-project worker API override (opt-in, fail-closed) ------------------ #

_PW = {
    "DANUS_PROJECT_PROJ17_WORKER_API_PROVIDER": None,
    "DANUS_PROJECT_PROJ17_WORKER_API_BASE_URL": None,
    "DANUS_PROJECT_PROJ17_WORKER_API_VERSION": None,
    "DANUS_PROJECT_PROJ17_WORKER_API_KEY": None,
}
_PW_FULL = {
    "DANUS_PROJECT_PROJ17_WORKER_API_PROVIDER": "azure",
    "DANUS_PROJECT_PROJ17_WORKER_API_BASE_URL": "https://YOUR_RESOURCE.cognitiveservices.azure.com/openai",
    "DANUS_PROJECT_PROJ17_WORKER_API_VERSION": "2025-04-01-preview",
    "DANUS_PROJECT_PROJ17_WORKER_API_KEY": "secret-key",
}


def test_project_worker_api_unset_is_noop():
    # No DANUS_PROJECT_* set → no profile, no extra argv, no injected key. This is
    # the existing-user path; it must be byte-identical to before the feature.
    with env(**_PW):
        assert codex.project_worker_api("Proj17") is None
        assert codex.project_worker_config_args("Proj17") == []
        assert "DANUS_PROJECT_WORKER_API_KEY" not in codex.subprocess_env(
            "/x/bin/codex", worker_project="Proj17")


def test_project_worker_api_full_profile_and_injection():
    with env(**_PW_FULL):
        p = codex.project_worker_api("Proj17")
        assert p is not None and p.provider == "azure" and p.api_key == "secret-key"
        args = codex.project_worker_config_args("Proj17")
        assert args[:2] == ["--config", 'model_provider="danus_project_worker"']
        assert any("model_providers.danus_project_worker=" in a for a in args)
        # the secret enters only via the neutral child env name, never argv
        assert not any("secret-key" in a for a in args)
        env_out = codex.subprocess_env("/x/bin/codex", worker_project="Proj17")
        assert env_out["DANUS_PROJECT_WORKER_API_KEY"] == "secret-key"


def test_project_worker_api_partial_fails_closed():
    partial = {**_PW_FULL, "DANUS_PROJECT_PROJ17_WORKER_API_KEY": None}
    with env(**partial):
        try:
            codex.project_worker_api("Proj17")
            assert False, "partial profile must raise"
        except ValueError:
            pass


def test_project_worker_api_rejects_non_azure():
    with env(**{**_PW_FULL, "DANUS_PROJECT_PROJ17_WORKER_API_PROVIDER": "openai"}):
        try:
            codex.project_worker_api("Proj17")
            assert False, "non-azure provider must raise"
        except ValueError:
            pass


def main() -> None:
    tests = [
        test_resolve_bin_prefers_danus_codex_bin_over_alias,
        test_resolve_bin_falls_back_to_wrapper_then_which_then_bare,
        test_resolve_bin_bare_when_nothing_available,
        test_model_override_wins_then_neutral_then_default,
        test_effort_override_wins_then_neutral_then_default,
        test_first_override_in_order_wins,
        test_subprocess_env_prepends_dir_for_concrete_path,
        test_subprocess_env_never_injects_cwd_for_bare_codex,
        test_subprocess_env_idempotent_when_dir_already_on_path,
        test_exec_cmd_shape_quoted_effort_and_verbatim_tail,
        test_exec_cmd_empty_tail,
        test_model_main_wins_over_codex_alias,
        test_project_worker_api_unset_is_noop,
        test_project_worker_api_full_profile_and_injection,
        test_project_worker_api_partial_fails_closed,
        test_project_worker_api_rejects_non_azure,
    ]
    for t in tests:
        t()
        print(f"  [ok] {t.__name__}")
    print("ALL CODEX LAUNCHER TESTS PASSED")


if __name__ == "__main__":
    main()
