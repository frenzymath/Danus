---
fact_id: fact_odd_recurrence
problem_id: odd-sum
author: example-worker
predecessors: []
glossary_introduces: {}
external_refs: []
---

## statement
Let $S(n) = 1 + 3 + 5 + \cdots + (2n-1)$ denote the sum of the first $n$ positive
odd numbers, for $n \ge 1$. Then $S(n+1) = S(n) + (2n+1)$ for every $n \ge 1$.

## proof
The $(n+1)$-th positive odd number is $2(n+1) - 1 = 2n+1$, and $S(n+1)$ is $S(n)$
plus that term.

## intuition
The partial sums advance by adding the next odd number, which is $2n+1$.
