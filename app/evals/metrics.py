import math


def recall_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    return len(expected & set(ranked[:k])) / len(expected)


def precision_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    return len(expected & set(ranked[:k])) / k


def reciprocal_rank(ranked: list[str], expected: set[str]) -> float:
    for position, item in enumerate(ranked, start=1):
        if item in expected:
            return 1 / position
    return 0.0


def ndcg_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(pos + 1) for pos, item in enumerate(ranked[:k], start=1) if item in expected)
    ideal = sum(1 / math.log2(pos + 1) for pos in range(1, min(len(expected), k) + 1))
    return dcg / ideal


RRF_K = 60


def reciprocal_rank_fusion(rankings: list[list[dict]], top_k: int, key: str) -> list[dict]:
    scores: dict = {}
    rows: dict = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            scores[row[key]] = scores.get(row[key], 0.0) + 1 / (RRF_K + rank)
            rows.setdefault(row[key], row)
    best = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [rows[item] for item in best]


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]