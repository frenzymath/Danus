"""local memory — per-worker private, rough "what I did" log.

Append-only JSONL channels + BM25 recall, deliberately rough: only process
channels (``notes`` / ``events``). The moment a thought becomes a formed claim
it is published to the shared **global memory** instead (see DATA_MODEL.md §1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import bm25
from ._util import append_jsonl, read_jsonl, utc_now

DEFAULT_CHANNELS = ("notes", "events")


class LocalMemory:
    """Rooted at a single worker's directory; private to that worker."""

    def __init__(self, root: Path, channels: Optional[List[str]] = None) -> None:
        # root is the worker's own dir; local memory lives under it.
        self.dir = Path(root) / "local_memory"
        self.channels = list(channels) if channels else list(DEFAULT_CHANNELS)

    def _path(self, channel: str) -> Path:
        return self.dir / f"{channel}.jsonl"

    def append(self, channel: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Append one rough record to a channel (creating it if new)."""
        if not isinstance(record, dict):
            raise ValueError("record must be a JSON object")
        if channel not in self.channels:
            self.channels.append(channel)
        entry = {"timestamp_utc": utc_now(), "channel": channel, "record": record}
        append_jsonl(self._path(channel), entry)
        # mirror a lightweight breadcrumb into `events` (audit log)
        if channel != "events":
            append_jsonl(
                self._path("events"),
                {"timestamp_utc": utc_now(), "event_type": "local_append", "channel": channel},
            )
        return {"status": "ok", "channel": channel, "path": str(self._path(channel)), "entry": entry}

    def read(self, channel: str) -> List[Dict[str, Any]]:
        return read_jsonl(self._path(channel))

    def search(
        self,
        query: str,
        channels: Optional[List[str]] = None,
        limit_per_channel: int = 10,
    ) -> Dict[str, Any]:
        """BM25 recall over this worker's own channels (default: all but events)."""
        search_channels = channels or [c for c in self.channels if c != "events"]
        out: Dict[str, Any] = {}
        for channel in search_channels:
            items = read_jsonl(self._path(channel))
            docs = [bm25.tokenize(json.dumps(it, ensure_ascii=False)) for it in items]
            scores = bm25.bm25_scores(query, docs)
            ranked = [
                {"score": s, "item": it}
                for it, s in sorted(zip(items, scores), key=lambda p: -p[1])
                if s > 0
            ][:limit_per_channel]
            out[channel] = {"count": len(ranked), "results": ranked}
        return {"query": query, "channels": search_channels, "results_by_channel": out}
