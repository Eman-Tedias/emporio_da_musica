import pytest

from app.evals.metrics import (
    dedupe, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank, reciprocal_rank_fusion,
)


def test_recall_and_precision_have_different_denominators():
    ranked, expected = ["a", "x", "b"], {"a", "b", "c", "d"}
    assert recall_at_k(ranked, expected, 3) == 0.5
    assert precision_at_k(ranked, expected, 3) == pytest.approx(2 / 3)

def test_reciprocal_rank_uses_the_first_hit():
    assert reciprocal_rank(["x", "a", "b"], {"a", "b"}) == 0.5
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0

def test_ndcg_rewards_better_order_that_recall_ignores():
    expected = {"a", "b"}
    assert ndcg_at_k(["a", "b", "x"], expected, 3) == 1.0
    assert ndcg_at_k(["x", "a", "b"], expected, 3) < 1.0
    assert recall_at_k(["x", "a", "b"], expected, 3) == 1.0

def test_rrf_rewards_items_found_by_both_rankings():
    first = [{"id": 1}, {"id": 2}]
    second = [{"id": 2}, {"id": 3}]
    assert reciprocal_rank_fusion([first, second], top_k=3, key="id")[0]["id"] == 2

def test_dedupe_keeps_first_occurrence():
    assert dedupe(["4.1", "4.2", "4.1", "3"]) == ["4.1", "4.2", "3"]