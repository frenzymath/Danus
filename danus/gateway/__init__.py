"""danus.gateway — the role-gated MCP server (the only door to the truth stores).

See ``server.build_app`` (constructs the stdio MCP app for a role) and ``roles``
(the permission table). Run as ``python -m danus.gateway``.
"""

from __future__ import annotations

from .roles import ALL_TOOLS, ROLE_TOOLS, tools_for
from .server import build_app

__all__ = ["build_app", "tools_for", "ROLE_TOOLS", "ALL_TOOLS"]
