---
fact_id: fact_odd_recurrence
problem_id: odd-sum
author: example-worker
predecessors: []
glossary_introduces:
  S(n): the sum of the first n positive odd numbers, S(n) = 1 + 3 + ... + (2n-1)
external_refs: [{"key": "AC24", "authors": ["A. Author", "B. Coauthor"], "title": "A note on telescoping sums", "venue": "J. Example Math.", "year": "2024", "cited_for": "the telescoping identity for consecutive partial sums"}]
---

## statement
For every integer $n \ge 1$, let $S(n) = 1 + 3 + 5 + \cdots + (2n-1)$ denote the sum of the first $n$ positive odd numbers, with $S(1) = 1$. Then $S(n+1) = S(n) + (2n+1)$ for all $n \ge 1$.

## proof
By definition $S(n) = \sum_{k=1}^{n} (2k-1)$. The $(n+1)$-st positive odd number is $2(n+1)-1 = 2n+1$. Hence
$$S(n+1) = \sum_{k=1}^{n+1} (2k-1) = \left( \sum_{k=1}^{n} (2k-1) \right) + (2n+1) = S(n) + (2n+1).$$
This is the one-step telescoping relation between consecutive partial sums; see \cite{AC24}.

## intuition
Passing from $S(n)$ to $S(n+1)$ just appends the next odd number, $2n+1$. This single-step recurrence is the only fact about the sums we will need.
