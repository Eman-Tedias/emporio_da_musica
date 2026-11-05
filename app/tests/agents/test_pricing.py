import pytest

from app.llm.pricing import cost_usd
from app.llm.providers import Usage


def test_cost_splits_input_and_output():
    cost = cost_usd("gemini-3.5-flash-lite", 2_000_000, 1_000_000)
    assert cost == pytest.approx({"input": 0.60, "output": 2.50, "total": 3.10})

def test_unknown_model_returns_none():
    assert cost_usd("some-new-model", 100, 100) is None

def test_usage_adds_up_across_tool_steps():
    assert Usage(10, 5) + Usage(3, 2) == Usage(13, 7)
