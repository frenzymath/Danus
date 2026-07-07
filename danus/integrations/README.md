# danus/integrations — arXiv theorem search

A thin, swappable adapter over external literature search. Currently one integration:
`matlas.py`, a stdlib-only client for **Matlas** arXiv theorem search, which returns
verbatim, as-published arXiv theorem/lemma/definition statements (statement fidelity
is load-bearing for math reasoning and citation checking).

```
danus/integrations/
  matlas.py       search(query, num_results=10, timeout=30) -> {query, count, results, endpoint[, error]}
  __init__.py     re-exports search + RESULT_FIELDS
  tests/test_integrations.py
```

## Contract

- `search(...)` **never raises** — on any failure it returns the same envelope with
  `results: []` and an `error` key (empty query, `http …`, `network: …`, bad JSON, …).
- Each result is normalized to exactly `("title", "theorem", "arxiv_id",
  "theorem_id")`, all coerced to `str`.
- Sends a real `User-Agent` (Cloudflare 403s otherwise); endpoint overridable via
  `MATLAS_URL`.

## Exposed as

The gateway wraps it as the MCP tool `search_arxiv_theorems(query, num_results)` — the
one tool **all three** roles (worker/main/verifier) can call for literature grounding.

## Known limitation (cross-module)

It returns theorem **statements**, not bibliographic metadata (authors/venue/year).
The write-paper reference verifier therefore uses the returned `arxiv_id` + a web
lookup for metadata. Keep this in mind if adding a citation-grounding consumer.

## Tests

`python -m pytest danus/integrations/` (offline; the HTTP call is mocked).
