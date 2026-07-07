"""danus.verify — the cold-start proof-verifier HTTP service (the sole write-gate).

``service.app`` is the FastAPI app (POST /verify, GET /health). Run as
``python -m danus.verify`` (or ``uvicorn danus.verify.service:app``).
"""

from __future__ import annotations

from .service import VerifyRequest, app
from .launcher import run_codex_verification
from .prechecks import run_prechecks

__all__ = ["app", "VerifyRequest", "run_codex_verification", "run_prechecks"]
