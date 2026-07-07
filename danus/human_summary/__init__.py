"""danus.human_summary — the human-summary MCP service.

Wraps the isolated report writer behind a single role-gated MCP tool
(``summary_write``) so the main agent gets a clean, human-facing progress report
``report.md`` **without authoring the prose itself and without reading the fact
files**. The large bytes (writer prompt + a scrubbed, id-free fact bundle) are
assembled inside the tool and never enter the main agent's context; the writer
codex runs isolated by construction (it reuses ``danus.authoring.driver``).

See ``assemble.build_prompt`` (the deterministic scrubbing assembler),
``server.build_app`` (the FastMCP app), and ``server.summary_write`` (the tool +
its leak check). Run as ``python -m danus.human_summary``.
"""

from __future__ import annotations

from .assemble import build_prompt
from .server import build_app, summary_write

__all__ = ["build_prompt", "build_app", "summary_write"]
