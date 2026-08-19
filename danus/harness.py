"""AgentAdapter protocol and the two proving-exec adapters.

Callers go through ``danus.codex`` (``get_adapter`` / ``exec_cmd`` /
``prepare_prompt``). This module holds the protocol so ``danus.codex`` stays a
thin facade. ``danus.dsh`` stays stdlib-only for the ``bin/codex-dsh`` script
invocation and is imported here only by ``DshAdapter``.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Protocol, Sequence

from danus.dsh import read_agent_default_model, rewrite_agent_default_model

_REPO_ROOT = Path(__file__).resolve().parents[1]


def exec_backend() -> str:
    """``CODEX_BACKEND`` at call time. Default ``api``."""
    return (os.environ.get("CODEX_BACKEND") or "api").strip().lower()


class AgentAdapter(Protocol):
    """Process adapter for one proving exec backend."""

    def prepare_prompt(
        self, prompt: str, *paths: Path, tools: Sequence[str] = (),
    ) -> str:
        ...

    def exec_argv(
        self, binary: str, model: str, effort: str, *tail: str,
    ) -> List[str]:
        ...

    def verify_results_root(
        self, *, agent_home: Path, package_runs: Path,
    ) -> Path:
        ...


class CodexAdapter:
    """Identity adapter: the historical ``codex exec`` argv and prompt."""

    def prepare_prompt(
        self, prompt: str, *paths: Path, tools: Sequence[str] = (),
    ) -> str:
        return prompt

    def exec_argv(
        self, binary: str, model: str, effort: str, *tail: str,
    ) -> List[str]:
        return [
            binary, "exec",
            "--model", model,
            "--config", f'model_reasoning_effort="{effort}"',
            *tail,
        ]

    def verify_results_root(
        self, *, agent_home: Path, package_runs: Path,
    ) -> Path:
        return Path(package_runs).resolve()


class DshAdapter:
    """Thin DeepSeek Harness adapter. Proving exec still goes through
    ``bin/codex-dsh``; consult reuses ``prepare_home`` / ``reclaim_home``."""

    def prepare_prompt(
        self, prompt: str, *paths: Path, tools: Sequence[str] = (),
    ) -> str:
        blocks = [prompt]
        for path in paths:
            if path.is_file():
                blocks.append(_instruction_block(path))
            elif path.is_dir():
                for skill in sorted(path.glob("**/SKILL.md")):
                    blocks.append(_instruction_block(skill))
        if tools:
            mapping = ", ".join(f"{name} -> mcp__danus__{name}" for name in tools)
            blocks.append(
                "Tool-name note: the danus gateway tools are exposed under "
                f"prefixed names — {mapping}."
            )
        return "\n\n".join(blocks)

    def exec_argv(
        self, binary: str, model: str, effort: str, *tail: str,
    ) -> List[str]:
        # Same argv shape as CodexAdapter; the shim drops flags headless lacks.
        return CodexAdapter().exec_argv(binary, model, effort, *tail)

    def verify_results_root(
        self, *, agent_home: Path, package_runs: Path,
    ) -> Path:
        return (agent_home / "runs").resolve()

    def prepare_home(
        self,
        src_home: Path,
        effort: str,
        *,
        model: Optional[str] = None,
        runtime: Optional[Path] = None,
        prefix: str = "consult",
    ) -> Path:
        """Copy creds/settings into a fresh per-call DSH_HOME and rewrite model."""
        if runtime is None:
            repo_runtime = _REPO_ROOT / "runtime"
            runtime = Path(os.environ.get("DANUS_RUNTIME") or str(repo_runtime))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        home = runtime / "dsh-runs" / f"{prefix}-{stamp}-{os.getpid()}"
        home.mkdir(parents=True, exist_ok=True)
        creds = src_home / ".credentials.yaml"
        if creds.is_file():
            shutil.copy2(creds, home / ".credentials.yaml")
            os.chmod(home / ".credentials.yaml", 0o600)
        settings_src = src_home / "settings.yaml"
        had_effort = False
        src_text = ""
        if settings_src.is_file():
            shutil.copy2(settings_src, home / "settings.yaml")
            src_text = settings_src.read_text(encoding="utf-8")
            had_effort = "reasoningEffort" in src_text
        src_provider, src_model = read_agent_default_model(src_text)
        provider = src_provider or "deepseek-official"
        model_out = model or src_model or "deepseek-v4-pro"
        effort_out = effort if had_effort else ""
        rewrite_agent_default_model(
            home / "settings.yaml", provider, model_out, effort_out,
        )
        return home

    @staticmethod
    def reclaim_home(home: Path) -> None:
        shutil.rmtree(home, ignore_errors=True)


def get_adapter() -> AgentAdapter:
    """The proving AgentAdapter selected by ``CODEX_BACKEND`` at call time."""
    if exec_backend() == "dsh":
        return DshAdapter()
    return CodexAdapter()


def _instruction_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return f'<instructions name="{path.name}">\n{text}\n</instructions>'
