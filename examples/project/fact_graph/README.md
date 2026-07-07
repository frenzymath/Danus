# fact_graph/ — illustrative sample data (NOT a verified run)

These two facts are **hand-authored sample data** that show the on-disk shape of a
Danus fact graph — they were written to `danus.core`'s real schema (so the
`fact_id`s are genuine content-addressed 16-hex digests and the frontmatter is
exactly what the engine reads), but they did **not** pass through the live
verifier. Do not treat them as verifier-accepted results.

Layout (per `danus/core/DATA_MODEL.md` §3):

```
fact_graph/
  facts/<fact_id>.md      one readable markdown file per fact; filename = bare-hex id
  glossary.json           accumulated project glossary (symbol -> definition)
```

The DAG here has two nodes:

- `3b0c70d292e73ebe` — the one-step recurrence $T(n+1) = T(n) + (n+1)$ (no
  predecessors).
- `8033e998b558da98` — the closed form $T(n) = n(n+1)/2$, whose `predecessors`
  list cites the recurrence fact. This is the "a proof may only build on
  fact-graph entries (cite a `fact_id`)" invariant in miniature.

Each `fact_id` is `SHA256(json{problem_id, sorted(predecessors),
sorted(glossary_introduces), normalized(statement), normalized(proof)})[:16]`, so
editing a statement or proof changes the id (and would orphan any dependent). To
regenerate this sample from source, add the two facts with `FactGraph.add(...)`
against `examples/project/` — see `danus/core/README.md`.

For a paper-pipeline example (a fact graph plus the polished LaTeX it compiles
to), see the write-paper skill's own toy project under
`agents/skills/write-paper/examples/paper/` rather than duplicating it here.
