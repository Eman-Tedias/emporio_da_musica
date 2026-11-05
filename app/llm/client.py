import logging
import time
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel

from app.config import get_settings
from app.llm.pricing import cost_usd
from app.llm.providers import GeminiProvider, OpenAIProvider, Provider, ToolExecutor
from app.observability import observe, update

logger = logging.getLogger("emporio.llm")


class LLMUnavailable(Exception):
    """Both the primary and the fallback model failed."""


@dataclass
class CallInfo:
    role: str
    model: str
    seconds: float
    fallback_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


def _trace_output(result):
    return result.model_dump() if isinstance(result, BaseModel) else result


@dataclass
class LLMClient:
    providers: dict[str, Provider]
    routes: dict[str, tuple[str, str]]
    max_tokens: dict[str, int]
    max_tool_steps: int = 5

    @staticmethod
    def provider_name(model: str) -> str:
        return "gemini" if model.startswith("gemini") else "openai"

    def _with_fallback(self, role: str, system: str, user: str, run):
        primary, fallback = self.routes[role]
        reason = None
        for model in (primary, fallback):
            start = time.perf_counter()
            with observe(role, as_type="generation", model=model, input={"system": system, "user": user},
                         metadata={"attempt": "primary" if model == primary else "fallback"}) as generation:
                try:
                    result, usage = run(self.providers[self.provider_name(model)], model)
                except Exception as error:
                    seconds = time.perf_counter() - start
                    reason = f"{model}: {type(error).__name__}: {str(error)[:200]}"
                    update(generation, level="ERROR", status_message=reason)
                    logger.warning("llm call failed role=%s model=%s seconds=%.2f error=%s",
                                   role, model, seconds, type(error).__name__)
                    continue
                cost = cost_usd(model, usage.input_tokens, usage.output_tokens)
                update(generation, output=_trace_output(result), cost_details=cost,
                       usage_details={"input": usage.input_tokens, "output": usage.output_tokens})
            info = CallInfo(role, model, round(time.perf_counter() - start, 2),
                            reason if model == fallback else None, usage.input_tokens, usage.output_tokens,
                            round(cost["total"], 6) if cost else None)
            if info.fallback_reason:
                logger.warning("llm fallback role=%s model=%s seconds=%.2f", role, model, info.seconds)
            return result, info
        logger.error("llm unavailable role=%s", role)
        raise LLMUnavailable(f"{role}: every model failed ({reason})")

    def structured(self, role: str, system: str, user: str, schema: type[BaseModel]) -> tuple[BaseModel, CallInfo]:
        return self._with_fallback(role, system, user, lambda provider, model: provider.structured(
            model, system, user, schema, self.max_tokens[role]))

    def tool_loop(self, role: str, system: str, user: str, tools: list[dict],
                  execute: ToolExecutor) -> tuple[str, CallInfo]:
        return self._with_fallback(role, system, user, lambda provider, model: provider.tool_loop(
            model, system, user, tools, execute, self.max_tool_steps, self.max_tokens[role]))


@lru_cache
def get_llm_client() -> LLMClient:
    settings = get_settings()
    return LLMClient(
        providers={
            "openai": OpenAIProvider(settings.openai_api_key.get_secret_value(), settings.llm_timeout_seconds),
            "gemini": GeminiProvider(settings.gemini_api_key.get_secret_value(), settings.llm_timeout_seconds),
        },
        routes={
            "guardrail": (settings.guardrail_model, settings.guardrail_fallback_model),
            "parser": (settings.parser_model, settings.parser_fallback_model),
            "data_agent": (settings.data_agent_model, settings.data_agent_fallback_model),
            "composer": (settings.composer_model, settings.composer_fallback_model),
        },
        max_tokens={"guardrail": 1000, "parser": 1500, "data_agent": 2000, "composer": 2000},
        max_tool_steps=settings.max_tool_steps,
    )
