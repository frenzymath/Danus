"""Spend ledger — the ONLY place money is recorded.

A project's total cost = the sum of ``cost_usd`` over ``<project>/spend/consult.jsonl``.
Append-only; malformed lines are tolerated when summing (skipped, never crash).
Even $0 entries are recorded (keeps the cadence/history complete).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

LEDGER_RELPATH = ("spend", "consult.jsonl")


def ledger_path(project: str) -> Path:
    return Path(project).joinpath(*LEDGER_RELPATH)


def log_spend(project: str, envelope: Dict[str, Any]) -> str:
    """Append one spend record for this consult and return the running total
    (formatted to 4 dp) over the whole ledger."""
    ledger = ledger_path(project)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    usage = envelope.get("usage") or {}
    rec = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "model": envelope.get("model"),
        "effort": envelope.get("effort"),
        "attempt": envelope.get("attempt"),
        "status": envelope.get("status"),
        "input_tokens": usage.get("input", 0),
        "output_tokens": usage.get("output", 0),
        "reasoning_tokens": usage.get("reasoning"),
        "cost_usd": envelope.get("cost_usd", 0.0),
        "seconds": envelope.get("seconds"),
    }
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return f"{_sum_ledger(ledger):.4f}"


def _sum_ledger(ledger: Path) -> float:
    total = 0.0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            total += float(json.loads(line).get("cost_usd", 0.0) or 0.0)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # tolerate malformed lines — never crash the sum
    return total
