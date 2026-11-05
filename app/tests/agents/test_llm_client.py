import pytest
from pydantic import BaseModel

from app.llm.client import LLMClient, LLMUnavailable
from app.llm.providers import SchemaError, Usage


class Answer(BaseModel):
    text: str


class FakeProvider:
    def __init__(self, error: Exception | None = None):
        self.error, self.calls = error, 0

    def structured(self, model, system, user, schema, max_tokens):
        self.calls += 1
        if self.error:
            raise self.error
        return Answer(text=model), Usage(1000, 500)

    def tool_loop(self, model, system, user, tools, execute, max_steps, max_tokens):
        answer, usage = self.structured(model, system, user, None, max_tokens)
        return answer.text, usage


def client(openai_error=None, gemini_error=None):
    return LLMClient(
        providers={"openai": FakeProvider(openai_error), "gemini": FakeProvider(gemini_error)},
        routes={"parser": ("gemini-x", "gpt-x")},
        max_tokens={"parser": 100},
    )


def test_primary_answers_when_healthy():
    answer, info = client().structured("parser", "s", "u", Answer)
    assert answer.text == "gemini-x" and info.fallback_reason is None

@pytest.mark.parametrize("error", [TimeoutError("timeout"), RuntimeError("429 quota"), SchemaError("bad json")])
def test_falls_back_to_the_other_provider(error):
    answer, info = client(gemini_error=error).structured("parser", "s", "u", Answer)
    assert answer.text == "gpt-x"
    assert type(error).__name__ in info.fallback_reason

def test_both_failing_raises():
    with pytest.raises(LLMUnavailable):
        client(TimeoutError(), TimeoutError()).structured("parser", "s", "u", Answer)

def test_tool_loop_also_falls_back():
    text, info = client(gemini_error=TimeoutError()).tool_loop("parser", "s", "u", [], lambda n, a: {})
    assert text == "gpt-x" and info.model == "gpt-x"

def test_provider_is_chosen_by_model_name():
    assert LLMClient.provider_name("gemini-3.5-flash-lite") == "gemini"
    assert LLMClient.provider_name("gpt-5.6-luna") == "openai"

def test_call_reports_tokens_and_cost():
    llm = LLMClient(
        providers={"openai": FakeProvider(), "gemini": FakeProvider()},
        routes={"parser": ("gpt-5.6-luna", "gemini-3.5-flash-lite")},
        max_tokens={"parser": 100},
    )
    _, info = llm.structured("parser", "s", "u", Answer)
    assert (info.input_tokens, info.output_tokens) == (1000, 500)
    # 1000 * 0.20 / 1M + 500 * 1.20 / 1M
    assert info.cost_usd == pytest.approx(0.0008)

def test_unknown_model_has_no_cost():
    _, info = client().structured("parser", "s", "u", Answer)
    assert info.cost_usd is None
