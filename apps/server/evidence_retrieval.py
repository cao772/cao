"""Model-free ranking and excerpts over already retrieved, authorized evidence."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


def lexical_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[a-z0-9]+(?:[._-][a-z0-9]+)*|[\u3400-\u9fff]+", text.lower()):
        word = match.group()
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            if len(word) > 1:
                tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
            else:
                tokens.append(word)
        else:
            tokens.append(word)
    return tokens


def bm25_scores(documents: list[str], query: str) -> list[float]:
    """BM25 (k1=1.2, b=.75) on the candidate set, not a full-corpus index."""
    terms = set(lexical_tokens(query))
    bags = [Counter(lexical_tokens(text)) for text in documents]
    lengths = [sum(bag.values()) for bag in bags]
    average = sum(lengths) / max(len(lengths), 1) or 1
    df = {term: sum(term in bag for bag in bags) for term in terms}
    scores = []
    for bag, length in zip(bags, lengths):
        score = 0.0
        for term in terms:
            frequency = bag.get(term, 0)
            if frequency:
                idf = math.log(1 + (len(bags) - df[term] + .5) / (df[term] + .5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / average))
        scores.append(score)
    return scores


def fuse_candidate_ranks(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Fuse existing field ranking with BM25 ranks; no raw-score scale assumptions."""
    if not rows:
        return []
    scores = bm25_scores(["\n".join(str(row.get(key) or "") for key in ("source_name", "source_path", "snippet")) for row in rows], query)
    # With punctuation-only queries, retain the original literal-match ordering.
    if not any(scores):
        return rows
    lexical_order = sorted((i for i in range(len(rows)) if scores[i] > 0), key=lambda i: (-scores[i], i))
    lexical_rank = {index: rank for rank, index in enumerate(lexical_order, 1)}
    result = []
    for index, row in enumerate(rows):
        rank = lexical_rank.get(index)
        fused = 1 / (60 + index + 1) + (1 / (60 + rank) if rank else 0)
        result.append({**row, "ranking_score": round(fused, 8), "lexical_score": round(scores[index], 5)})
    return sorted(result, key=lambda row: (row["ranking_score"], row["lexical_score"]), reverse=True)


def evidence_excerpt(text: str, query: str, limit: int = 500) -> str:
    """Center the excerpt on a literal query hit, retaining original source text."""
    lowered = text.lower()
    terms = query.lower().split()
    positions = [lowered.find(term) for term in terms if term and term in lowered]
    position = min(positions) if positions else 0
    start = max(0, position - min(120, limit // 3))
    end = min(len(text), start + limit)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def literal_like(term: str) -> str:
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
