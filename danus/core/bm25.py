"""BM25 ranking over JSONL entries — the memory search behind local/global
memory recall.

The only known weakness is that the corpus is re-tokenized and re-scored on
every call (no persistent index); swapping in a persistent index (e.g. sqlite
FTS5) is a future optimization that must preserve this ranking's behavior.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import List

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def bm25_scores(
    query: str,
    documents: List[List[str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> List[float]:
    """Return one BM25 score per (already tokenized) document for ``query``."""
    query_tokens = tokenize(query)
    if not query_tokens or not documents:
        return [0.0 for _ in documents]

    query_term_counts = Counter(query_tokens)
    document_frequencies: Counter = Counter()
    document_term_counts = [Counter(doc) for doc in documents]
    document_lengths = [len(doc) for doc in documents]
    avg_doc_length = sum(document_lengths) / len(document_lengths) if document_lengths else 0.0
    total_documents = len(documents)

    for doc in documents:
        for token in set(doc):
            document_frequencies[token] += 1

    scores: List[float] = []
    for doc_counts, doc_length in zip(document_term_counts, document_lengths):
        score = 0.0
        norm = k1 * (1.0 - b + b * (doc_length / avg_doc_length)) if avg_doc_length > 0 else k1
        for token, query_tf in query_term_counts.items():
            tf = doc_counts.get(token, 0)
            if tf <= 0:
                continue
            df = document_frequencies.get(token, 0)
            idf = math.log(1.0 + ((total_documents - df + 0.5) / (df + 0.5)))
            score += query_tf * idf * (tf * (k1 + 1.0)) / (tf + norm)
        scores.append(score)
    return scores
