"""Run the verify service: ``python -m danus.verify`` (default 127.0.0.1:8091)."""

from __future__ import annotations

import os

if __name__ == "__main__":
    import uvicorn

    from .service import app

    # This launcher entrypoint supplies a bounded per-verification codex time
    # unless the operator overrides; the library default (launcher._timeout)
    # stays 0/None (= no timeout) for in-process use.
    os.environ.setdefault("CODEX_TIMEOUT_SECONDS", "900")
    host = os.getenv("VERIFY_HOST", "127.0.0.1")
    port = int(os.getenv("VERIFY_PORT", os.getenv("PORT", "8091")))
    uvicorn.run(app, host=host, port=port)
