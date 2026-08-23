#!/usr/bin/env python3
"""Seed a paper's REFERENCE_LEDGER from the project's verified facts.

This is the payoff of the structured ``external_refs`` field: every fact records
the published results its proof cited (key / authors / title / arxiv / year /
cited_for), so the bibliography is aggregated *from the source* instead of being
re-mined from prose by an LLM (the recorded #1 failure mode — citation
hallucination). Dedups by citation key (falling back to arXiv id), records every
fact that cites each reference, and marks each row ``verified-by: unverified`` so
the reference auditor knows what still needs an independent check.

**Scoped to the SAME target closure as the writer.** By default the ledger is
seeded from ONLY the paper's target-closure facts — the recorded target (the
brief's ``headline_fact_ids``, or the finalized ``<project>/TARGET.md``, or an
explicit ``--headline``) plus their transitive predecessors — the identical
closure ``assemble.fact_graph_content`` embeds for the writer. This is what keeps
phantom rows out of the ledger: seeding from all facts (including proven-but-unused
side lemmas) would list references the paper never cites.
If no target is recorded, the seed REFUSES (matching the writer, which will not
guess). Pass ``--all-facts`` to seed from every fact regardless of the closure.

    python3 seed_ledger.py <project_dir>                       # closure ledger → the paper workspace
    python3 seed_ledger.py <project_dir> --out L.md
    python3 seed_ledger.py <project_dir> --headline fact_a fact_b
    python3 seed_ledger.py <project_dir> --paper thmA          # a non-default paper's workspace
    python3 seed_ledger.py <project_dir> --all-facts           # legacy: every fact

The output is a starting point, not the final bibliography: the auditor verifies
authors/title/venue/year/arXiv id and flips ``unverified`` to ``verified``.

Multiple papers per project (Item B): ``--paper <paper_id>`` scopes the closure to
that paper's recorded target (its own brief / TARGET.md under
``<project>/papers/<paper_id>/``) and, with no ``--out``, writes the ledger into
that paper's workspace — keeping each paper's ledger in lockstep with its own
closure. The default paper keeps the legacy ``<project>/paper/`` workspace.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from danus.core import FactGraph
from danus.write_paper import assemble


def _ref_key(ref: dict) -> str:
    return str(ref.get("key") or ref.get("arxiv") or ref.get("title") or "UNKEYED").strip()


def closure_fact_ids(project_dir: Path, headline=None, paper_id=None):
    """The target closure: the resolved headline (arg > brief > finalized
    ``<paper>/TARGET.md``) plus its transitive predecessors — the SAME set the
    writer embeds (via ``assemble``). This is the single closure both the ledger
    and the writer share, and it stays in lockstep PER PAPER (``paper_id`` roots
    the brief + TARGET.md at the paper's workspace).

    Reuses ``assemble.resolve_headline`` + ``assemble._toposort_with_predecessors``
    — the EXACT closure the writer uses; there is no second closure path here.

    When the target is UNSET (no arg, no brief field, no TARGET.md) this raises
    ``assemble.TargetUnsetError`` — the ledger does NOT fall back to seeding from
    all facts. Pass ``--all-facts`` (the explicit legacy escape) for that."""
    fg = FactGraph(project_dir)
    resolved, source = assemble.resolve_headline(project_dir, headline, paper_id)
    if source == "unset":
        raise assemble.TargetUnsetError(
            "no paper target is set: pass --headline, set headline_fact_ids in "
            "PROJECT_BRIEF.md, or run `danus finalize <project> [--paper <id>] "
            "<fact_id>` to record TARGET.md (or use --all-facts for the legacy "
            "all-facts seed)"
        )
    return assemble._toposort_with_predecessors(fg, resolved)


def collect(project_dir: Path, headline=None, all_facts: bool = False,
            paper_id=None) -> dict:
    """key -> {ref fields merged, cited_by: [fact_id...]}.

    Scoped to the target closure by default (``all_facts=False``): only facts on
    the paper's closure contribute their ``external_refs``. ``all_facts=True``
    restores the legacy behavior (every fact in the graph). ``paper_id`` selects
    which paper's target closure (default → the legacy paths)."""
    fg = FactGraph(project_dir)
    fids = fg.list() if all_facts else closure_fact_ids(project_dir, headline, paper_id)
    out: dict = {}
    for fid in fids:
        for ref in fg.external_refs(fid):
            if not isinstance(ref, dict):
                continue
            k = _ref_key(ref)
            row = out.setdefault(k, {"key": k, "cited_by": []})
            for field, val in ref.items():
                if val and not row.get(field):
                    row[field] = val
            if fid not in row["cited_by"]:
                row["cited_by"].append(fid)
    return out


def _fmt_authors(a) -> str:
    if isinstance(a, list):
        return ", ".join(str(x) for x in a)
    return str(a or "")


def render(rows: dict) -> str:
    lines = [
        "# REFERENCE_LEDGER",
        "",
        "Seeded from the project's verified facts' `external_refs`. Each row is a",
        "published result some proof cited. `verified-by: unverified` rows still",
        "need an independent check by the reference auditor (authors / title /",
        "venue / year / arXiv id). Do not fabricate; flag what cannot be verified.",
        "",
    ]
    if not rows:
        lines += ["_(no external references captured on any fact yet)_", ""]
        return "\n".join(lines)
    for k in sorted(rows):
        r = rows[k]
        lines.append(f"## {k}")
        if r.get("authors"):
            lines.append(f"- authors: {_fmt_authors(r.get('authors'))}")
        for field in ("title", "arxiv", "year", "venue", "doi"):
            if r.get(field):
                lines.append(f"- {field}: {r[field]}")
        cited = ", ".join(r["cited_by"]) or "—"
        lines.append(f"- cited_by_facts: {cited}")
        lines.append("- verified-by: unverified")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Seed REFERENCE_LEDGER from a project's facts (target closure by default).")
    p.add_argument("project_dir", help="the project directory (holds fact_graph/)")
    p.add_argument("--out", help="write here instead of stdout")
    p.add_argument("--headline", nargs="*", default=None,
                   help="target fact ids (the paper's headline results); default = "
                        "the brief's headline_fact_ids, else the finalized "
                        "<project>/TARGET.md. The ledger is scoped to this closure. "
                        "If none is set the seed refuses (use --all-facts to override).")
    p.add_argument("--all-facts", action="store_true",
                   help="legacy: seed from EVERY fact regardless of the closure "
                        "(may list references the paper never cites).")
    p.add_argument("--paper", default=None,
                   help="the paper_id (multiple papers per project). Default / 'main' "
                        "→ the legacy <project>/paper/ workspace; else "
                        "<project>/papers/<paper_id>/. Scopes the target closure and "
                        "(with no --out) the ledger's write location to that paper.")
    args = p.parse_args(argv)

    pdir = Path(args.project_dir)
    if not (pdir / "fact_graph").is_dir():
        sys.stderr.write(f"seed_ledger: no fact_graph/ under {pdir}\n")
        return 2
    try:
        text = render(collect(pdir, headline=args.headline, all_facts=args.all_facts,
                              paper_id=args.paper))
    except assemble.TargetUnsetError as e:
        sys.stderr.write(f"seed_ledger: {e}\n")
        return 3
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        # No --out: default the ledger into the paper's own workspace so the
        # per-paper ledger stays in lockstep with that paper's closure.
        ws = assemble.paper_workspace(pdir, args.paper)
        ledger = ws / "REFERENCE_LEDGER.md"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(text, encoding="utf-8")
        print(f"wrote {ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
