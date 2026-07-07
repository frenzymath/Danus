"""Run the write-paper service as a stdio MCP server:
``python -m danus.write_paper``.

Launched by ``bin/write-paper-mcp`` (which exports DANUS_WRITE_PAPER_SKILL_DIR and the
codex/project env).
"""

from .server import build_app

if __name__ == "__main__":
    build_app().run()
