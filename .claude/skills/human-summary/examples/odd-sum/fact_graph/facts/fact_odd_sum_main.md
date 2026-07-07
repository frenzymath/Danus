---
fact_id: fact_odd_sum_main
problem_id: odd-sum
author: example-worker
predecessors: [fact_odd_recurrence, fact_square_recurrence]
glossary_introduces: {}
external_refs: []
---

## statement
For every integer $n \ge 1$, the sum of the first $n$ positive odd numbers equals
$n^2$; that is, $S(n) = n^2$, where $S(n) = 1 + 3 + 5 + \cdots + (2n-1)$.

## proof
By induction on $n$. Base case: $S(1) = 1 = 1^2$. Inductive step: suppose
$S(n) = n^2$ for some $n \ge 1$. By the partial-sum recurrence,
$S(n+1) = S(n) + (2n+1) = n^2 + (2n+1)$. By the square recurrence,
$n^2 + (2n+1) = (n+1)^2$. Hence $S(n+1) = (n+1)^2$, completing the induction.

## intuition
Both $S(n)$ and $n^2$ start at $1$ and grow by the same increment $2n+1$ at each
step, so they coincide for all $n$.
