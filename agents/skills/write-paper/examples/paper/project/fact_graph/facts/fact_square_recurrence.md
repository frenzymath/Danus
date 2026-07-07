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
Expanding the square, $(n+1)^2 = n^2 + 2n + 1 = n^2 + (2n+1)$.

## intuition
The perfect squares grow by the consecutive odd numbers: the gap between $n^2$ and $(n+1)^2$ is exactly $2n+1$. This is the same increment that appears in the recurrence for $S(n)$.
