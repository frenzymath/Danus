"""Handshake-probe the three Danus MCP servers exactly as a dsh mcp-client
would: initialize + list tools over stdio.

Usage: python scripts/dsh_mcp_probe.py <repo> [role]

Exits 0 when all three servers list their tools, non-zero otherwise. Used by
scripts/apply-dsh-mcp.sh and runnable standalone. Needs the ``mcp`` package
(the bootstrap venv python).

The three servers are the same ``<repo>/bin/*-mcp`` wrappers the
examples/dsh-integration/cordis.patch.yml.example rows name, with the same env
(DANUS_ROLE / DANUS_AUTHOR), so a green run here is strong evidence the profile
rows will load.
"""

from __future__ import annotations

import asyncio
import os
import sys

SERVERS = ("danus", "write-paper", "human-summary")


async def probe(label: str, command: str, env_extra: dict) -> list:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print(f"{label} -> SKIPPED (python has no 'mcp' package; run scripts/bootstrap.sh)")
        return []
    params = StdioServerParameters(command=command, args=[], env=env_extra)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
        print(f"{label} -> OK, {len(names)} tools: {names}")
        return names
    except Exception as exc:  # noqa: BLE001 — one line per server, never a traceback
        print(f"{label} -> FAILED: {type(exc).__name__}: {exc}")
        return []


async def main() -> int:
    repo = sys.argv[1]
    role = sys.argv[2] if len(sys.argv) > 2 else "main"
    common = {"DANUS_ROLE": role, "DANUS_AUTHOR": "main_agent"}
    failures = 0
    for name in SERVERS:
        names = await probe(name, os.path.join(repo, "bin", name + "-mcp"), dict(common))
        if not names:
            failures += 1
    print("DSH-MCP-PROBE: " + ("ALL OK" if failures == 0 else f"{failures} FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
