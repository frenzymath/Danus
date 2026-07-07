"""Provide a ``tmp`` fixture (a fresh temp dir Path) for the execution tests, so
each test function reads identically whether run under pytest or the standalone
``main()`` runner (which passes a Path directly)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
