"""Danus verify service — the sole write-gate's HTTP front.

    POST /verify {statement, proof} -> {verification_report, verdict, repair_hints}
    GET  /health                    -> {status: "ok", pid: <int>}

/verify runs the deterministic pre-checks (``prechecks.run_prechecks``) and, if
they pass, cold-starts a fresh codex verifier (``launcher.run_codex_verification``)
whose verdict the gateway's ``fact_submit`` uses to decide whether a claim becomes
a fact. The verifier is an LLM, NOT a formal proof assistant, with no human in the
loop by default — see the verifier contract (``agents/contracts/verifier.md``).
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .launcher import _allocate_run_id, run_codex_verification
from .prechecks import run_prechecks


class VerifyRequest(BaseModel):
    statement: str = Field(..., min_length=1)
    proof: str = Field(..., min_length=1)


app = FastAPI(title="Danus verify service", version="0.1.0")


@app.get("/health")
async def health() -> Dict[str, Any]:
    # async on purpose: /health must not queue behind sync /verify threadpool
    # calls, so it responds in ~microseconds regardless of in-flight verifications.
    # `pid` self-identifies this instance: a health probe alone cannot tell OUR
    # verify from another deployment's verify holding the same port on a shared
    # host — callers match this pid against runtime/run/verify.pid to be sure.
    return {"status": "ok", "pid": os.getpid()}


@app.post("/verify")
def verify(request: VerifyRequest) -> Dict[str, Any]:
    rejected = run_prechecks(request.statement, request.proof)
    if rejected is not None:
        status_code, detail = rejected
        raise HTTPException(status_code=status_code, detail=detail)
    run_id = _allocate_run_id(request.statement)
    return run_codex_verification(run_id=run_id, statement=request.statement, proof=request.proof)
