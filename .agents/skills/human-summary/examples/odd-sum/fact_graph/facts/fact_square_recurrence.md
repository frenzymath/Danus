---
fact_id: fact_square_recurrence
problem_id: odd-sum
author: example-worker
predecessors: []
glossary_introduces: {}
external_refs: []
---

## statement
For every integer $n \ge 1$, $(n+1)^2 = n^2 + (2n+1)$.

## proof
Expand $(n+1)^2 = n^2 + 2n + 1 = n^2 + (2n+1)$.

## intuition
Squares grow by consecutive odd increments: the gap from $n^2$ to $(n+1)^2$ is
exactly the $(n+1)$-th odd number, $2n+1$.
