"""global memory — project-shared, strongly typed findings.

One append-only JSONL file per kind (one file per channel, shared) + BM25.
Each entry is a *claim plus its evidence* with a ``verifiable`` tag and a
``status``. See DATA_MODEL.md §2.

Deliberately thin: append / read / search the JSONL, plus a small append-only
``status`` note. *When* to publish, verify, or promote is prose (prompts), not
code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import bm25
from ._util import append_jsonl, read_jsonl, utc_now
from .schema import GLOBAL_KINDS, STATUSES

_STATUS_LOG = "_status.jsonl"  # append-only status transitions


class GlobalMemory:
    """Rooted at the project directory; shared by all workers + the main agent."""

    def __init__(self, root: Path) -> None:
        self.dir = Path(root) / "global_memory"

    def _path(self, kind: str) -> Path:
        return self.dir / f"{kind}.jsonl"

    # ------------------------------------------------------------------ write
    def append(
        self,
        kind: str,
        claim: str,
        evidence: str,
        author: str,
        *,
        verifiable: Optional[bool] = None,
        links: Optional[Dict[str, Any]] = None,
        glossary: Optional[Dict[str, str]] = None,
        **extra: Any,
    ) -> str:
        """Publish a finding (claim + evidence). Returns its id.

        ``verifiable`` defaults to the kind's default; objectively-checkable
        kinds require non-empty ``evidence`` (a proof/construction). ``glossary``
        (symbol -> definition) is optional but encouraged: define your symbols
        and reuse the project's terminology, so the finding stays readable and
        carries cleanly into a fact (DATA_MODEL.md §2 writing guideline).
        """
        if kind not in GLOBAL_KINDS:
            raise ValueError(f"unknown kind '{kind}'. Known: {sorted(GLOBAL_KINDS)}")
        if verifiable is None:
            verifiable = GLOBAL_KINDS[kind]
        if verifiable and not (evidence or "").strip():
            raise ValueError(f"kind '{kind}' is verifiable and requires explicit evidence")
        ts = utc_now()
        entry_id = hashlib.sha256(
            json.dumps([kind, claim, author, ts], ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        append_jsonl(
            self._path(kind),
            {
                "id": entry_id,
                "timestamp_utc": ts,
                "author": author,
                "kind": kind,
                "claim": claim,
                "evidence": evidence,
                "verifiable": verifiable,
                "status": "unverified" if verifiable else "open",
                "fact_id": None,
                "links": links or {},
                "glossary": glossary or {},
                **extra,
            },
        )
        return entry_id

    def set_status(self, entry_id: str, status: str, fact_id: Optional[str] = None) -> None:
        """Record a status transition (append-only)."""
        if status not in STATUSES:
            raise ValueError(f"invalid status '{status}'. Valid: {STATUSES}")
        append_jsonl(
            self.dir / _STATUS_LOG,
            {"timestamp_utc": utc_now(), "id": entry_id, "status": status, "fact_id": fact_id},
        )

    # ------------------------------------------------------------------- read
    def _latest_status(self) -> Dict[str, Dict[str, Any]]:
        latest: Dict[str, Dict[str, Any]] = {}
        for rec in read_jsonl(self.dir / _STATUS_LOG):
            if rec.get("id"):
                latest[rec["id"]] = rec  # file is chronological; last wins
        return latest

    def read(self, kind: str) -> List[Dict[str, Any]]:
        """All entries of a kind, with the latest status folded in."""
        latest = self._latest_status()
        out = []
        for e in read_jsonl(self._path(kind)):
            st = latest.get(e.get("id"))
            if st:
                e = {**e, "status": st["status"], "fact_id": st.get("fact_id") or e.get("fact_id")}
            out.append(e)
        return out

    def search(
        self, query: str, kinds: Optional[List[str]] = None, limit_per_kind: int = 10
    ) -> Dict[str, Any]:
        """BM25 over the chosen kinds (default: all)."""
        latest = self._latest_status()
        out: Dict[str, Any] = {}
        for kind in (kinds or list(GLOBAL_KINDS)):
            entries = read_jsonl(self._path(kind))
            docs = [bm25.tokenize(json.dumps(e, ensure_ascii=False)) for e in entries]
            scores = bm25.bm25_scores(query, docs)
            ranked = []
            for e, s in sorted(zip(entries, scores), key=lambda p: -p[1]):
                if s <= 0:
                    break
                st = latest.get(e.get("id"))
                if st:
                    e = {**e, "status": st["status"], "fact_id": st.get("fact_id") or e.get("fact_id")}
                ranked.append({"score": s, "entry": e})
                if len(ranked) >= limit_per_kind:
                    break
            out[kind] = {"count": len(ranked), "results": ranked}
        return {"query": query, "results_by_kind": out}
