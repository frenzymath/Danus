"""arXiv theorem search (Matlas).

Matlas does semantic retrieval of **verbatim** theorem / lemma / definition
statements from arXiv, each tagged with its ``arxiv_id`` and in-paper
``theorem_id``. Statements are returned **as published** — statement fidelity
matters for math reasoning and citation checking.

Implementation uses stdlib ``urllib`` (no ``requests`` dependency) and degrades
gracefully — it never raises, so a search outage cannot crash a worker/verifier
round (returns an ``error`` with an empty ``results`` list instead).

API (no auth):
  POST https://leansearch.net/thm/search  {"query": str, "task": str, "num_results": int}
       -> 200, a JSON **list**; each item normalized to
          {title, theorem, arxiv_id, theorem_id}

Env:
  MATLAS_URL   override the endpoint (default https://leansearch.net/thm/search)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

_URL = os.environ.get("MATLAS_URL", "https://leansearch.net/thm/search")

# The retrieval task the endpoint conditions on.
_TASK = (
    "Given a math statement, retrieve useful references, such as theorems, "
    "lemmas, and definitions, that are useful for solving the given problem."
)

_DEFAULT_TIMEOUT = 30

# The fields each normalized result carries.
RESULT_FIELDS = ("title", "theorem", "arxiv_id", "theorem_id")


def search(query: str, num_results: int = 10, timeout: int = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Search arXiv theorem statements matching ``query`` (a math statement).

    Returns ``{"query", "count", "results": [{title, theorem, arxiv_id,
    theorem_id}, ...], "endpoint"}``. On any failure returns the same envelope
    with ``error`` set and ``results: []`` (never raises)."""
    q = (query or "").strip()
    if not q:
        return {"query": query, "count": 0, "results": [], "endpoint": _URL, "error": "empty query"}
    n = int(num_results) if num_results and int(num_results) > 0 else 10
    payload = json.dumps({"query": q, "task": _TASK, "num_results": n}).encode("utf-8")
    req = urllib.request.Request(
        _URL, data=payload, method="POST",
        # the endpoint sits behind Cloudflare, which 403s urllib's default
        # bare request — an explicit User-Agent + Accept gets through.
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "danus/1.0 (+https://frenzymath.com)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted service)
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"query": q, "count": 0, "results": [], "endpoint": _URL, "error": f"http {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"query": q, "count": 0, "results": [], "endpoint": _URL, "error": f"network: {e.reason}"}
    except (TimeoutError, json.JSONDecodeError, ValueError) as e:
        return {"query": q, "count": 0, "results": [], "endpoint": _URL, "error": f"{type(e).__name__}: {e}"}

    if not isinstance(data, list):
        return {"query": q, "count": 0, "results": [], "endpoint": _URL,
                "error": f"theorem endpoint must return a JSON list, got {type(data).__name__}"}

    results: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title", "")),
            "theorem": str(item.get("theorem", "")),
            "arxiv_id": str(item.get("arxiv_id", "")),
            "theorem_id": str(item.get("theorem_id", "")),
        })
    return {"query": q, "count": len(results), "results": results, "endpoint": _URL}


if __name__ == "__main__":  # smoke: python3 -m danus.integrations.matlas "your statement"
    import sys

    out = search(sys.argv[1] if len(sys.argv) > 1
                 else "compact Kähler manifold with nef canonical bundle")
    print(f"count={out['count']}  error={out.get('error')}")
    for r in out["results"][:3]:
        print(f"- {r['arxiv_id']} {r['theorem_id']} | {r['title'][:55]}: {r['theorem'][:100]}")
