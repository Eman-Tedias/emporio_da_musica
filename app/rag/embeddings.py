from functools import lru_cache

from openai import OpenAI

from app.config import get_settings
from app.llm.pricing import cost_usd
from app.observability import observe, update


@lru_cache
def get_openai_client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key.get_secret_value())


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_settings().embedding_model
    trace_input = texts[0] if len(texts) == 1 else f"{len(texts)} texts"
    with observe("embedding", as_type="embedding", model=model, input=trace_input) as embedding:
        response = get_openai_client().embeddings.create(model=model, input=texts)
        tokens = response.usage.prompt_tokens if response.usage else 0
        update(embedding, usage_details={"input": tokens}, cost_details=cost_usd(model, tokens, 0))
    return [item.embedding for item in response.data]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def to_pgvector(embedding: list[float]) -> str:
    return "[" + ",".join(map(str, embedding)) + "]"
