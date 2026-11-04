import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean

from app.config import get_settings
from app.rag.chunker import Chunk, chunk_pdf
from app.rag.embeddings import embed_texts
from app.rag.ingest import POLICIES_FILE
from app.rag.retriever import search_policies
from app.tools.db import agent_connection
from app.evals.metrics import (
    dedupe, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank, reciprocal_rank_fusion,
)

EVALS_DIR = Path(__file__).parent
GOLDEN_SET = EVALS_DIR / "retrieval_golden_set.json"
RESULTS_DIR = EVALS_DIR / "results"
CACHE_FILE = EVALS_DIR / ".cache" / "embeddings.json"
K_VALUES = (1, 3)
CANDIDATES = 30
CHARS_PER_TOKEN = 4  #estimate for Portuguese

LEXICAL_QUERY = """
    SELECT u.idx AS unit_id
      FROM unnest(%(texts)s::text[]) WITH ORDINALITY AS u(text, idx),
           to_tsquery('portuguese', %(terms)s) AS query
     WHERE to_tsvector('portuguese', u.text) @@ query
     ORDER BY ts_rank(to_tsvector('portuguese', u.text), query) DESC
     LIMIT %(limit)s
"""


class EmbeddingCache:
    def __init__(self, path: Path, model: str):
        self.path, self.model = path, model
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\n{text}".encode()).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(t for t in texts if self._key(t) not in self.data))
        if missing:
            for text, vector in zip(missing, embed_texts(missing)):
                self.data[self._key(text)] = vector
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return [self.data[self._key(t)] for t in texts]


class InMemoryIndex:

    def __init__(self, units: list[tuple[str, str]], cache: EmbeddingCache):
        self.units = units
        self.vectors = cache.embed([text for _, text in units])

    def semantic(self, query_vector: list[float]) -> list[dict]:
        scored = sorted(
            ((sum(a * b for a, b in zip(query_vector, v)), i) for i, v in enumerate(self.vectors)),
            reverse=True,
        )[:CANDIDATES]
        return [{"unit_id": i + 1, "similarity": s} for s, i in scored]

    def lexical(self, question: str) -> list[dict]:
        words = re.findall(r"\w+", question.lower())
        if not words:
            return []
        with agent_connection() as conn:
            return conn.execute(LEXICAL_QUERY, {
                "texts": [text for _, text in self.units], "terms": " | ".join(words), "limit": CANDIDATES,
            }).fetchall()

    def sections(self, rows: list[dict]) -> list[str]:
        return dedupe([self.units[row["unit_id"] - 1][0] for row in rows])


def normalize_text(text: str) -> str:
    text = text.replace("<br>", " ").replace("**", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def score_case(ranked: list[str], case: dict, by_number: dict[str, Chunk]) -> dict:
    expected = set(case["expected_sections"])
    delivered = " ".join(by_number[s].content for s in ranked[:3] if s in by_number)
    return {
        **{f"recall@{k}": recall_at_k(ranked, expected, k) for k in K_VALUES},
        **{f"precision@{k}": precision_at_k(ranked, expected, k) for k in K_VALUES},
        "mrr": reciprocal_rank(ranked, expected),
        "ndcg@3": ndcg_at_k(ranked, expected, 3),
        "evidence@3": float(normalize_text(case["evidence"]) in normalize_text(delivered)),
        "tokens@3": len(delivered) / CHARS_PER_TOKEN,
        "evidence_density": len(case["evidence"]) / max(len(by_number[s].content) for s in expected),
    }


def run(include_holdout: bool) -> None:
    settings = get_settings()
    cases = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    if not include_holdout:
        cases = [c for c in cases if not c["holdout"]]

    cache = EmbeddingCache(CACHE_FILE, settings.embedding_model)
    chunks = chunk_pdf(settings.data_dir / POLICIES_FILE)
    by_number = {c.section_number: c for c in chunks}
    sections = InMemoryIndex([(c.section_number, c.text_for_embedding) for c in chunks], cache)
    pieces = InMemoryIndex([(c.section_number, t) for c in chunks for t in c.pieces_for_embedding], cache)
    vectors = dict(zip([c["question"] for c in cases], cache.embed([c["question"] for c in cases])))

    def hybrid(index: InMemoryIndex, q: str, v: list[float]) -> list[str]:
        fused = reciprocal_rank_fusion([index.semantic(v), index.lexical(q)], CANDIDATES, key="unit_id")
        return index.sections(fused)

    strategies = {
        "section_semantic": lambda q, v: sections.sections(sections.semantic(v)),
        "section_hybrid": lambda q, v: hybrid(sections, q, v),
        "small_to_big_semantic": lambda q, v: pieces.sections(pieces.semantic(v)),
        "small_to_big_hybrid": lambda q, v: hybrid(pieces, q, v),
        "production": lambda q, v: [r["section_number"] for r in search_policies(q, top_k=5, embedding=v)],
    }

    rows = []
    for name, rank in strategies.items():
        for case in cases:
            vector = vectors[case["question"]]
            ranked = rank(case["question"], vector)
            row = {"strategy": name, "id": case["id"], "category": case["category"], "ranked": ranked[:5]}
            if case["expected_sections"]:
                row |= score_case(ranked, case, by_number)
            if name == "small_to_big_semantic":
                row["top1_similarity"] = pieces.semantic(vector)[0]["similarity"]
            rows.append(row)

    answerable = [r for r in rows if "mrr" in r]
    metrics = ["recall@1", "recall@3", "precision@1", "precision@3", "mrr", "ndcg@3", "evidence@3", "tokens@3"]
    print(f"\n{len({r['id'] for r in answerable})} answerable questions "
          f"(holdout {'included' if include_holdout else 'excluded'})\n")
    print("| strategy | " + " | ".join(metrics) + " |")
    print("|---|" + "---|" * len(metrics))
    for name in strategies:
        scored = [r for r in answerable if r["strategy"] == name]
        print(f"| {name} | " + " | ".join(f"{mean(r[m] for r in scored):.3f}" for m in metrics) + " |")

    categories = sorted({r["category"] for r in answerable})
    print("\nrecall@1 by category")
    print("| strategy | " + " | ".join(categories) + " |")
    print("|---|" + "---|" * len(categories))
    for name in strategies:
        values = [mean(r["recall@1"] for r in answerable if r["strategy"] == name and r["category"] == c)
                  for c in categories]
        print(f"| {name} | " + " | ".join(f"{v:.2f}" for v in values) + " |")

    reference = [r for r in rows if r["strategy"] == "small_to_big_semantic"]
    positives = [r["top1_similarity"] for r in reference if r["category"] != "negative"]
    negatives = [r["top1_similarity"] for r in reference if r["category"] == "negative"]
    if negatives:
        print(f"\ntop-1 similarity: answerable mean {mean(positives):.3f} (min {min(positives):.3f}), "
              f"negative mean {mean(negatives):.3f} (max {max(negatives):.3f})")
    print(f"evidence density: mean {mean(r['evidence_density'] for r in reference if 'mrr' in r):.3f}")
    print(f"index sizes: {len(sections.units)} sections, {len(pieces.units)} pieces")

    production = {r["id"]: r["ranked"][:3] for r in rows if r["strategy"] == "production"}
    expected = {r["id"]: r["ranked"][:3] for r in reference}
    mismatches = [i for i in production if production[i] != expected[i]]
    print(f"production matches small_to_big_semantic: {not mismatches}"
          + (f" (differs on {mismatches})" if mismatches else ""))

    print("\nmisses at recall@1 (expected -> top 3)")
    for r in answerable:
        if r["recall@1"] < 1 and r["strategy"] != "production":
            case = next(c for c in cases if c["id"] == r["id"])
            print(f"  {r['strategy']:<22} {r['id']} {case['expected_sections']} -> {r['ranked'][:3]}")

    RESULTS_DIR.mkdir(exist_ok=True)
    output = RESULTS_DIR / f"retrieval_{datetime.now():%Y%m%d_%H%M%S}.json"
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nper-question results: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-holdout", action="store_true")
    run(parser.parse_args().include_holdout)