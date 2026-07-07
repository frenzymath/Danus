"""Run the danus gateway as a stdio MCP server: ``python -m danus.gateway``.

Role is taken from ``DANUS_ROLE`` (env). Launched by ``bin/danus-mcp`` (main) and
by each worker's ``.codex/config.toml`` (worker) / the verifier's ``-c`` override.
"""

from .server import build_app

if __name__ == "__main__":
    build_app().run()
