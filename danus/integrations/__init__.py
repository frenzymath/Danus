"""danus.integrations — external services the engine grounds proofs against.

Currently: arXiv theorem search via ``matlas``. Kept as a thin, swappable
adapter — ``search`` is the stable surface a future worker can back with another
provider without touching the gateway.
"""

from __future__ import annotations

from .matlas import RESULT_FIELDS, search

__all__ = ["search", "RESULT_FIELDS"]
