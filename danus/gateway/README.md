# danus/gateway — role-gated MCP server (the permission gate)

The **only sanctioned door to the truth stores.** A stdio MCP server (`danus-core`)
whose exposed tools depend on the caller's role — permission is enforced by *which
tools a role can even see*, not by prompt convention.

```
danus/gateway/
  server.py            the 6 MCP tools + the fact_submit write-gate; build_app(role)
  roles.py             ROLE_TOOLS — the role→tools table (the security surface)
  __main__.py          `python -m danus.gateway` → build_app().run() (role from DANUS_ROLE)
  tests/test_gateway.py
```

## The role table (`roles.py`)

| role | tools |
|---|---|
| worker | `gm_add gm_search fact_submit fact_search search_arxiv_theorems` |
| main | `gm_add gm_search fact_search fact_revoke search_arxiv_theorems` (**no `fact_submit`**) |
| verifier | `search_arxiv_theorems` only (read-only) |

Ungated tools are **physically absent** from the surface. Unknown, mis-typed, or
*unset* role → **fail-closed** to the verifier set; the full dev set requires the
explicit `DANUS_ROLE=all`.

## The write-gate (`fact_submit`, in `server.py`)

The single path a fact enters truth: (1) call the verify service
(`DANUS_VERIFY_URL`); (2) **write the fact iff `verdict == "correct"`**; (3) **always**
trace the verdict to global memory. Service unreachable / non-dict body → clean error,
nothing written. The gate trusts the verdict string; it does not recompute it.

## Launched by

`bin/danus-mcp` (role=main, for Claude Code via `.mcp.json`); each worker's
`.codex/config.toml` (role=worker); the verify launcher injects it (role=verifier) so
the judge can call `search_arxiv_theorems`. Config (`DANUS_PROJECT_DIR`,
`DANUS_AGENTS_ROOT`, `DANUS_VERIFY_URL`, role, author) is read at **call time**.

## Pinned interfaces (ARCHITECTURE §4 — change both ends together)

The 6-tool set + role table; `python -m danus.gateway` launch; the verify HTTP seam.

## Tests

`python -m pytest danus/gateway/` (offline; the verify call is stubbed).
