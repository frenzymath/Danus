"""Role -> allowed-tools table — the permission skeleton of the whole system.

This is the single, first-class source of truth for separation of duties: which
MCP tools each agent role may even see. It is data (easy to audit / change), not
logic scattered across the server.

Invariants (load-bearing — see ARCHITECTURE.md §3):
  - ``main`` has NO ``fact_submit``: the orchestrator does no math and can never
    fabricate a fact.
  - ``verifier`` is read-only: only ``search_arxiv_theorems`` (it reads the fact
    graph as files, writes nothing).
  - ``worker`` is the only role that can ``fact_submit`` (verifier-gated write).
All three roles get ``search_arxiv_theorems`` (literature grounding); ``worker``
and ``main`` additionally get ``fact_search`` (read view over verified facts).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# All tools the gateway can expose (names must match the functions registered in
# server.py). Kept here so the role table and the implementation can't drift.
ALL_TOOLS: Tuple[str, ...] = (
    "gm_add",
    "gm_search",
    "fact_submit",
    "fact_search",
    "fact_revoke",
    "search_arxiv_theorems",
)

ROLE_TOOLS: Dict[str, Tuple[str, ...]] = {
    "worker": ("gm_add", "gm_search", "fact_submit", "fact_search", "search_arxiv_theorems"),
    "main": ("gm_add", "gm_search", "fact_search", "fact_revoke", "search_arxiv_theorems"),
    "verifier": ("search_arxiv_theorems",),
    "all": ALL_TOOLS,
}


def tools_for(role: str) -> List[str]:
    """The tool names a given role may use. An unknown / misconfigured role falls
    back to the most-restrictive read-only set (``verifier``), so a typo can never
    grant write access (fail-closed); the full set requires the explicit
    ``"all"`` key (dev use)."""
    return list(ROLE_TOOLS.get(role, ROLE_TOOLS["verifier"]))
