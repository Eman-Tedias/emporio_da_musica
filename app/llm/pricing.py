"""List prices in USD per 1M tokens, sent to Langfuse as the cost of each call.

Source: provider pricing as reported by third-party aggregators, checked on 2026-11-04. Gemini calls on
the free tier are not billed; the list price shows what the same traffic would cost in production.
"""

PRICES: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "text-embedding-3-small": (0.02, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> dict[str, float] | None:
    prices = PRICES.get(model)
    if prices is None:
        return None
    input_cost = input_tokens * prices[0] / 1_000_000
    output_cost = output_tokens * prices[1] / 1_000_000
    return {"input": input_cost, "output": output_cost, "total": input_cost + output_cost}
