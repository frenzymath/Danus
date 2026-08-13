"""The single shared codex launcher — one uniform CALL + env contract.

Every place Danus execs codex (the proving workers in ``danus.execution.loop``,
the verify service in ``danus.verify.launcher``, and the one-shot artifact
renderers in ``danus.authoring.driver``) resolves the codex binary, the model,
the reasoning effort, the subprocess environment, and the ``exec`` command prefix
**through this module** — so the four are uniform across the three sites and there
is exactly one place to change any of them.

All config is read at CALL time (never import time), so services stay
testable/reconfigurable.

Env contract (neutral defaults + back-compat aliases):
  CODEX_BACKEND       exec backend: api | chatgpt (the codex CLI, default) | dsh
                      (DeepSeek Harness headless via bin/codex-dsh)
  DANUS_CODEX_BIN     codex binary; back-compat alias: CODEX_BIN
  DANUS_CODEX_MODEL   neutral default model (default "gpt-5.5")
  DANUS_CODEX_EFFORT  neutral default reasoning effort (default "xhigh")

Each site layers its own per-service override env names on top of the neutral
defaults via ``model(*overrides)`` / ``effort(*overrides)`` (e.g. the verify
service passes ``DANUS_VERIFY_MODEL``; the renderers pass
``DANUS_WRITE_PAPER_MODEL`` / ``DANUS_HUMAN_SUMMARY_MODEL``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List

# danus/codex.py → repo root is one parent up; the deployment's bin/codex wrapper
# lives at <repo>/bin/codex.
_REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODEL = "gpt-5.5"
DEFAULT_EFFORT = "xhigh"


def backend() -> str:
    """The exec backend selected by ``CODEX_BACKEND`` at CALL time.

    ``api`` / ``chatgpt`` (the default ``api``) both exec the codex
    CLI — they differ only in how codex authenticates, which the CLI itself
    decides. ``dsh`` execs DeepSeek Harness headless sessions instead, via
    the ``bin/codex-dsh`` shim (one ``dsh --profile headless`` run per
    ``codex exec`` call; the same argv + exit-code contract).
    """
    return (os.environ.get("CODEX_BACKEND") or "api").strip().lower()


def _resolve_override(override: str) -> str:
    """An absolute ``DANUS_CODEX_BIN`` override is used as-is; a
    bare/relative name is resolved to its absolute path via PATH so
    subprocess_env can prepend its dir for the ``#!/usr/bin/env node``
    shebang. Falls back to the raw override (exec then surfaces a clear
    FileNotFoundError)."""
    if os.path.isabs(override):
        return override
    return shutil.which(override) or override


def resolve_bin() -> str:
    """Resolve the exec binary at CALL time. Precedence:
      1. ``DANUS_CODEX_BIN`` env,
      2. the backend's binary — ``<repo>/bin/codex-dsh`` when
         ``CODEX_BACKEND=dsh``, else ``<repo>/bin/codex`` if it exists,
      3. ``shutil.which("codex")`` (or ``"codex-dsh"``),
      4. the bare string ``"codex"`` / ``"codex-dsh"`` (so a missing
         binary raises a clear FileNotFoundError at exec time, not import time).
    """
    override = os.environ.get("DANUS_CODEX_BIN")
    if override:
        return _resolve_override(override)
    dsh = backend() == "dsh"
    name = "codex-dsh" if dsh else "codex"
    wrapper = _REPO_ROOT / "bin" / name
    if wrapper.exists():
        return str(wrapper)
    which = shutil.which(name)
    if which:
        return which
    return name


def model(*override_env_names: str, default: str = DEFAULT_MODEL) -> str:
    """The codex model: first non-empty among the given per-service override env
    vars (in order), then the neutral ``DANUS_CODEX_MODEL``, then ``default``."""
    for name in override_env_names:
        val = os.environ.get(name)
        if val:
            return val
    return os.environ.get("DANUS_CODEX_MODEL") or default


def effort(*override_env_names: str, default: str = DEFAULT_EFFORT) -> str:
    """The reasoning effort: first non-empty among the given per-service override
    env vars (in order), then the neutral ``DANUS_CODEX_EFFORT``, then
    ``default``."""
    for name in override_env_names:
        val = os.environ.get(name)
        if val:
            return val
    return os.environ.get("DANUS_CODEX_EFFORT") or default


def subprocess_env(codex_bin: str) -> Dict[str, str]:
    """A copy of ``os.environ`` with the codex binary's DIR prepended to ``PATH``
    so its ``#!/usr/bin/env node`` shebang resolves regardless of how the caller
    was launched.

    Only augments PATH when ``codex_bin`` has a directory component (a concrete
    path); the bare ``"codex"`` fallback must NOT inject the CWD into the
    subprocess PATH.
    """
    env = os.environ.copy()
    if os.path.dirname(codex_bin):
        codex_dir = os.path.dirname(os.path.abspath(codex_bin))
        if codex_dir and codex_dir != ".":
            existing = env.get("PATH", "")
            parts = existing.split(os.pathsep) if existing else []
            if codex_dir not in parts:
                env["PATH"] = codex_dir + (os.pathsep + existing if existing else "")
    return env


def exec_cmd(codex_bin: str, model: str, effort: str, *tail: str) -> List[str]:
    """The uniform ``codex exec`` command prefix + the caller's exact tail.

    Standardizes on the QUOTED reasoning-effort config form
    (``model_reasoning_effort="<effort>"``). The ``*tail`` is passed through
    verbatim (each site keeps its own exact tail: sandbox flags, ``-C`` home,
    MCP ``-c`` injection, output path, the ``-`` stdin sentinel, the prompt, …).
    """
    return [
        codex_bin, "exec",
        "--model", model,
        "--config", f'model_reasoning_effort="{effort}"',
        *tail,
    ]


def dsh_context(prompt: str, *paths: Path) -> str:
    """Embed a site's contract + skills into the prompt — for backend=``dsh``
    only.

    The codex CLI auto-loads ``AGENTS.md`` from the working dir and discovers
    skills under ``.agents/skills``; DeepSeek Harness headless has neither, so
    the same files are appended verbatim as a bounded context block. Any other
    backend gets the prompt back unchanged (codex reads the files itself).
    Files are embedded whole; directories contribute every ``SKILL.md`` under
    them in sorted order.
    """
    if backend() != "dsh":
        return prompt
    blocks = [prompt]
    for path in paths:
        if path.is_file():
            blocks.append(_dsh_block(path))
        elif path.is_dir():
            for skill in sorted(path.glob("**/SKILL.md")):
                blocks.append(_dsh_block(skill))
    return "\n\n".join(blocks)


def _dsh_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return f'<instructions name="{path.name}">\n{text}\n</instructions>'
