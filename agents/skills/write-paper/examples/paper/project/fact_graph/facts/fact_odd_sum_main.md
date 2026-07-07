---
fact_id: fact_odd_sum_main
problem_id: odd-sum
author: example-worker
predecessors: [fact_odd_recurrence, fact_square_recurrence]
glossary_introduces: {}
external_refs: [{"key": "Exm20", "authors": ["C. Example"], "title": "Elementary induction, revisited", "venue": "Example Lecture Notes", "year": "2020", "cited_for": "the principle of mathematical induction in the form used here"}]
---

## statement
For every integer $n \ge 1$, the sum of the first $n$ positive odd numbers equals $n^2$; that is, $S(n) = n^2$, where $S(n) = 1 + 3 + 5 + \cdots + (2n-1)$.

## proof
We argue by induction on $n$, in the form recalled in \cite{Exm20}.

Base case. For $n = 1$ we have $S(1) = 1 = 1^2$.

Inductive step. Suppose $S(n) = n^2$ for some $n \ge 1$. By the recurrence for the partial sums, $S(n+1) = S(n) + (2n+1)$. Substituting the inductive hypothesis gives $S(n+1) = n^2 + (2n+1)$. By the recurrence for the squares, $n^2 + (2n+1) = (n+1)^2$. Hence $S(n+1) = (n+1)^2$, completing the induction.

## intuition
Both $S(n)$ and $n^2$ start at $1$ and grow by the same increment $2n+1$ at each step, so they agree for all $n$. The induction simply records that two sequences with equal initial value and equal one-step increments coincide.
