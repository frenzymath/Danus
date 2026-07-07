"""Offline tests for danus.codex.subprocess_env — the PATH-augmentation branch.

Zero network / codex. Confirms the codex binary's dir is prepended to PATH for a
concrete path (so its ``#!/usr/bin/env node`` shebang resolves), and that the bare
``"codex"`` fallback does NOT inject anything into PATH.

Runs standalone (``python -m danus.tests.test_codex_env``) and under pytest.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from danus import codex


def test_subprocess_env_prepends_dir_for_concrete_path():
    env = codex.subprocess_env("/opt/tools/codex")
    assert env["PATH"].split(os.pathsep)[0] == "/opt/tools"
    # the rest of the original PATH is preserved after the prepended dir
    assert os.environ.get("PATH", "") in env["PATH"]


def test_subprocess_env_bare_name_does_not_touch_path():
    before = os.environ.get("PATH", "")
    env = codex.subprocess_env("codex")
    assert env.get("PATH", "") == before  # no dir component -> PATH unchanged


def test_subprocess_env_returns_full_environ_copy():
    env = codex.subprocess_env("/x/y/codex")
    # it is a copy of the whole environment, not just PATH
    assert env is not os.environ
    for k in os.environ:
        if k != "PATH":
            assert env[k] == os.environ[k]


def _no_override_no_wrapper(which_result):
    """Run resolve_bin() with no override env and no bin/codex wrapper, with
    shutil.which stubbed to ``which_result``. Returns resolve_bin()'s result."""
    saved = {n: os.environ.pop(n, None) for n in ("DANUS_CODEX_BIN", "CODEX_BIN")}
    orig_root, orig_which = codex._REPO_ROOT, shutil.which
    try:
        with tempfile.TemporaryDirectory() as d:
            codex._REPO_ROOT = Path(d)  # a dir with no bin/codex wrapper
            shutil.which = lambda name: which_result
            return codex.resolve_bin()
    finally:
        codex._REPO_ROOT, shutil.which = orig_root, orig_which
        for n, v in saved.items():
            if v is not None:
                os.environ[n] = v


def test_resolve_bin_falls_through_to_which():
    assert _no_override_no_wrapper("/usr/bin/codex") == "/usr/bin/codex"


def test_resolve_bin_falls_through_to_bare_codex():
    assert _no_override_no_wrapper(None) == "codex"


def main() -> None:
    test_subprocess_env_prepends_dir_for_concrete_path()
    print("  [ok] subprocess_env prepends the codex dir to PATH for a concrete path")
    test_subprocess_env_bare_name_does_not_touch_path()
    print("  [ok] subprocess_env leaves PATH untouched for the bare 'codex' fallback")
    test_subprocess_env_returns_full_environ_copy()
    print("  [ok] subprocess_env returns a full os.environ copy")
    test_resolve_bin_falls_through_to_which()
    print("  [ok] resolve_bin falls through to which('codex') when no override/wrapper")
    test_resolve_bin_falls_through_to_bare_codex()
    print("  [ok] resolve_bin returns bare 'codex' when nothing resolves")
    print("ALL CODEX-ENV TESTS PASSED")


if __name__ == "__main__":
    main()
