"""danus.observability — the strictly read-only dashboard.

A single self-contained FastAPI app that re-parses one project's on-disk stores
(fact graph + global memory + optional spend ledger) and serves a one-page
browser view. Imports no danus.core runtime module; only ever reads files.

    python -m danus.observability --project <dir> [--port 8099]

See ``app.py`` for the server + parsers.
"""

from __future__ import annotations

from .app import (
    CHANNELS,
    app,
    build_channel,
    build_channels,
    build_factgraph,
    build_overview,
    main,
)

__all__ = [
    "app",
    "main",
    "CHANNELS",
    "build_overview",
    "build_factgraph",
    "build_channels",
    "build_channel",
]
