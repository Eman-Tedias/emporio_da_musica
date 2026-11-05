import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.prompts import DATA_AGENT
from app.agents.delimiters import Delimiter
from app.calculators.rules import shipping_quote, simulate_installments
from app.llm.client import CallInfo, LLMClient
from app.observability import observe, update
from app.tools.calculate import calculate
from app.tools.catalog import get_product, list_active_promotions, list_categories, search_products

logger = logging.getLogger("emporio.data_agent")

class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchProductsArgs(StrictArgs):
    category: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    term: str | None = None
    only_available: bool = True


class GetProductArgs(StrictArgs):
    name: str = Field(max_length=120)


class NoArgs(StrictArgs):
    pass


class InstallmentsArgs(StrictArgs):
    total: Decimal = Field(gt=0)
    installments: int = Field(ge=1, le=24)


class ShippingArgs(StrictArgs):
    order_total: Decimal = Field(gt=0)
    city: str = Field(max_length=80)


class CalculateArgs(StrictArgs):
    expression: str = Field(max_length=200)


def _to_dict(value):
    return asdict(value) if hasattr(value, "__dataclass_fields__") else value


TOOLS = {
    "search_products": (SearchProductsArgs, lambda a: search_products(**a.model_dump())),
    "get_product": (GetProductArgs, lambda a: get_product(a.name)),
    "list_categories": (NoArgs, lambda a: list_categories()),
    "list_active_promotions": (NoArgs, lambda a: list_active_promotions()),
    "simulate_installments": (InstallmentsArgs, lambda a: simulate_installments(a.total, a.installments)),
    "shipping_quote": (ShippingArgs, lambda a: shipping_quote(a.order_total, a.city)),
    "calculate": (CalculateArgs, lambda a: {"expression": a.expression, "result": calculate(a.expression)}),
}

STRING, NUMBER, INTEGER, BOOLEAN = ({"type": t} for t in ("string", "number", "integer", "boolean"))

TOOL_SPECS = [
    {"name": "search_products", "description": "Search the catalog. Prices are the card price after active "
        "promotions. Hides out-of-stock and discontinued products unless only_available is false.",
     "parameters": {"type": "object", "properties": {
         "category": STRING, "min_price": NUMBER, "max_price": NUMBER, "term": STRING, "only_available": BOOLEAN}}},
    {"name": "get_product", "description": "Find one product by approximate name. Returns prices (card and "
        "PIX), availability, promotion and maximum installments, or candidates when ambiguous.",
     "parameters": {"type": "object", "properties": {"name": STRING}, "required": ["name"]}},
    {"name": "list_categories", "description": "Categories and how many products are available in each.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "list_active_promotions", "description": "Products with an active promotion and their prices.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "simulate_installments", "description": "Checks an installment plan against the store minimums.",
     "parameters": {"type": "object", "properties": {"total": NUMBER, "installments": INTEGER},
                    "required": ["total", "installments"]}},
    {"name": "shipping_quote", "description": "Shipping fee and delivery time for an order total and city.",
     "parameters": {"type": "object", "properties": {"order_total": NUMBER, "city": STRING},
                    "required": ["order_total", "city"]}},
    {"name": "calculate", "description": "Arithmetic (+ - * / parentheses) over numbers taken from tool "
        "results, e.g. a cart total. Use a dot as decimal separator.",
     "parameters": {"type": "object", "properties": {"expression": STRING}, "required": ["expression"]}},
]


@dataclass
class DataAgentResult:
    summary: str
    tool_results: list[dict] = field(default_factory=list)
    call: CallInfo | None = None


def execute_tool(name: str, raw_args: dict, log: list[dict]) -> dict:
    """Validates the arguments the LLM produced before anything touches the database."""
    if name not in TOOLS:
        return {"error": f"unknown tool {name}"}
    model, run = TOOLS[name]
    start = time.perf_counter()
    with observe(name, as_type="tool", input=raw_args) as tool:
        try:
            args = model(**raw_args)
            result = _to_dict(run(args))
        except (ValidationError, ValueError) as error:
            result = {"error": str(error)[:300]}
        update(tool, output=result, **({"level": "WARNING"} if "error" in result else {}))
    seconds = round(time.perf_counter() - start, 3)
    logger.debug("tool name=%s seconds=%.3f error=%s", name, seconds, "error" in result)
    log.append({"tool": name, "args": raw_args, "result": result, "seconds": seconds})
    return result if isinstance(result, dict) else {"items": result}


def run_data_agent(llm: LLMClient, question: str) -> DataAgentResult:
    log: list[dict] = []
    tags = Delimiter()
    summary, call = llm.tool_loop(
        "data_agent", tags.system(DATA_AGENT), tags.block("question", question), TOOL_SPECS,
        lambda name, args: execute_tool(name, args, log),
    )
    return DataAgentResult(summary, log, call)