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
  DANUS_CODEX_BIN     codex binary; back-compat alias: CODEX_BIN
  DANUS_MAIN_MODEL    neutral default model for every danus-spawned codex call
                      (default "gpt-5.6-sol"); back-compat alias: DANUS_CODEX_MODEL
  DANUS_MAIN_EFFORT   neutral default reasoning effort (default "xhigh");
                      back-compat alias: DANUS_CODEX_EFFORT

Each site layers its own per-service override env names on top of the neutral
defaults via ``model(*overrides)`` / ``effort(*overrides)`` (e.g. the workers pass
``DANUS_WORKER_MODEL``; the verify service passes ``DANUS_VERIFY_MODEL``; the
renderers pass ``DANUS_WRITE_PAPER_MODEL`` / ``DANUS_HUMAN_SUMMARY_MODEL``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# danus/codex.py → repo root is one parent up; the deployment's bin/codex wrapper
# lives at <repo>/bin/codex.
_REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "xhigh"

_PROJECT_WORKER_KEY_ENV = "DANUS_PROJECT_WORKER_API_KEY"


@dataclass(frozen=True)
class ProjectWorkerApi:
    """One optional API override selected from the worker's project name."""

    provider: str
    base_url: str
    api_version: str
    api_key: str


def _project_worker_prefix(project: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", project).strip("_").upper()
    if not token:
        raise ValueError("worker project name has no environment-safe characters")
    return f"DANUS_PROJECT_{token}_WORKER_API_"


def project_worker_api(project: str) -> Optional[ProjectWorkerApi]:
    """Return a project-scoped worker API override, if configured.

    Secrets remain in the gitignored ``config/codex.env`` and enter Codex only
    through the child environment. A partial profile fails closed instead of
    silently sending that project's traffic through the shared default API.
    """
    prefix = _project_worker_prefix(project)
    names = {
        "provider": prefix + "PROVIDER",
        "base_url": prefix + "BASE_URL",
        "api_version": prefix + "VERSION",
        "api_key": prefix + "KEY",
    }
    values = {field: os.environ.get(name, "").strip() for field, name in names.items()}
    if not any(values.values()):
        return None
    missing = [names[field] for field, value in values.items() if not value]
    if missing:
        raise ValueError(
            f"incomplete worker API profile for project {project!r}; missing "
            + ", ".join(missing)
        )
    if values["provider"].lower() != "azure":
        raise ValueError(
            f"unsupported worker API provider for project {project!r}: "
            f"{values['provider']!r} (supported: azure)"
        )
    return ProjectWorkerApi(**values)


def project_worker_config_args(project: str) -> List[str]:
    """Codex CLI overrides for a project's worker-only model provider.

    Provider/auth keys in a cwd-local ``.codex/config.toml`` are intentionally
    ignored by Codex. Command-line config is machine-local precedence, while the
    credential itself is referenced by environment-variable name and never put
    in argv.
    """
    profile = project_worker_api(project)
    if profile is None:
        return []
    provider_id = "danus_project_worker"
    provider = (
        f"model_providers.{provider_id}={{"
        'name="Danus project worker Azure",'
        f"base_url={json.dumps(profile.base_url)},"
        'wire_api="responses",'
        f"query_params={{api-version={json.dumps(profile.api_version)}}},"
        f'env_http_headers={{"api-key"="{_PROJECT_WORKER_KEY_ENV}"}},'
        "supports_websockets=false}"
    )
    return [
        "--config", f'model_provider="{provider_id}"',
        "--config", provider,
    ]


def resolve_bin() -> str:
    """Resolve the codex binary at CALL time. Precedence:
      1. ``DANUS_CODEX_BIN`` env,
      2. ``<repo>/bin/codex`` wrapper if it exists,
      3. ``shutil.which("codex")``,
      4. the bare string ``"codex"`` (so a missing binary raises a clear
         FileNotFoundError at exec time, not import time).
    """
    override = os.environ.get("DANUS_CODEX_BIN")
    if override:
        # An absolute override is used as-is; a bare/relative name is resolved to
        # its absolute path via PATH so subprocess_env can prepend its dir for the
        # codex ``#!/usr/bin/env node`` shebang. Fall back to the raw override if
        # it is not on PATH (exec then surfaces a clear FileNotFoundError).
        if os.path.isabs(override):
            return override
        return shutil.which(override) or override
    wrapper = _REPO_ROOT / "bin" / "codex"
    if wrapper.exists():
        return str(wrapper)
    which = shutil.which("codex")
    if which:
        return which
    return "codex"


def model(*override_env_names: str, default: str = DEFAULT_MODEL) -> str:
    """The codex model: first non-empty among the given per-service override env
    vars (in order), then the neutral ``DANUS_MAIN_MODEL`` (back-compat alias
    ``DANUS_CODEX_MODEL``), then ``default``."""
    for name in override_env_names:
        val = os.environ.get(name)
        if val:
            return val
    return (
        os.environ.get("DANUS_MAIN_MODEL")
        or os.environ.get("DANUS_CODEX_MODEL")
        or default
    )


def effort(*override_env_names: str, default: str = DEFAULT_EFFORT) -> str:
    """The reasoning effort: first non-empty among the given per-service override
    env vars (in order), then the neutral ``DANUS_MAIN_EFFORT`` (back-compat alias
    ``DANUS_CODEX_EFFORT``), then ``default``."""
    for name in override_env_names:
        val = os.environ.get(name)
        if val:
            return val
    return (
        os.environ.get("DANUS_MAIN_EFFORT")
        or os.environ.get("DANUS_CODEX_EFFORT")
        or default
    )


def subprocess_env(codex_bin: str, *, worker_project: Optional[str] = None) -> Dict[str, str]:
    """A copy of ``os.environ`` with the codex binary's DIR prepended to ``PATH``
    so its ``#!/usr/bin/env node`` shebang resolves regardless of how the caller
    was launched.

    Only augments PATH when ``codex_bin`` has a directory component (a concrete
    path); the bare ``"codex"`` fallback must NOT inject the CWD into the
    subprocess PATH.

    When ``worker_project`` names a project with a configured per-project worker
    API profile, the profile's key is injected under the neutral child-only env
    name ``DANUS_PROJECT_WORKER_API_KEY`` (referenced by the inline provider
    config from ``project_worker_config_args``). The shared Azure/OpenAI vars used
    by main agents, verifiers, and renderers are left untouched.
    """
    env = os.environ.copy()
    if os.path.dirname(codex_bin):
        codex_dir = os.path.dirname(os.path.abspath(codex_bin))
        if codex_dir and codex_dir != ".":
            existing = env.get("PATH", "")
            parts = existing.split(os.pathsep) if existing else []
            if codex_dir not in parts:
                env["PATH"] = codex_dir + (os.pathsep + existing if existing else "")
    if worker_project is not None:
        profile = project_worker_api(worker_project)
        if profile is not None:
            env[_PROJECT_WORKER_KEY_ENV] = profile.api_key
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
