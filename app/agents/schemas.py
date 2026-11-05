from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["catalog", "order", "policy", "out_of_scope", "greeting"]


class GuardrailVerdict(BaseModel):
    suspicious: bool
    reason: str = Field(max_length=300)


class ParsedRequest(BaseModel):
    intents: list[Intent] = Field(min_length=1)
    rewritten_question: str = Field(max_length=500)
    product: str | None = None
    category: str | None = None
    max_price: float | None = None
    order_id: int | None = None


class ComposedAnswer(BaseModel):
    answer: str = Field(max_length=2500)
    cited_sections: list[str] = Field(default_factory=list)