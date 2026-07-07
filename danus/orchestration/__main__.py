"""Run the danus CLI: ``python -m danus.orchestration <verb> …`` (bin/danus execs this)."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
