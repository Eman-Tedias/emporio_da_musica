import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.agents import prompts
from app.agents.data_agent import run_data_agent
from app.agents.delimiters import Delimiter
from app.agents.schemas import ComposedAnswer, GuardrailVerdict, ParsedRequest
from app.config import get_settings
from app.guardrails.input import check_input
from app.guardrails.output import check_output
from app.guardrails.policy import load_policy
from app.guardrails.session import SessionState
from app.llm.client import LLMClient, LLMUnavailable
from app.rag.retriever import search_policies
from app.tools.orders import get_order

STORE_TIMEZONE = ZoneInfo("America/Campo_Grande")

DISPATCH = {
    "catalog": {"data"},
    "order": {"order"},
    "policy": {"policies"},
    "out_of_scope": {"policies"},
    "greeting": set(),
}


@dataclass
class TurnResult:
    answer: str
    trace: dict = field(default_factory=dict)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _history_text(session: SessionState, turns: int) -> str:
    lines = [f"{m['role']}: {m['text']}" for m in session.history[-turns * 2:]]
    return "\n".join(lines) or "(no previous messages)"


class Orchestrator:
    def __init__(
        self,
        llm: LLMClient,
        data_agent: Callable = run_data_agent,
        policy_search: Callable = search_policies,
        order_lookup: Callable = get_order,
        now: Callable[[], datetime] = lambda: datetime.now(STORE_TIMEZONE),
    ):
        self.llm, self.data_agent, self.policy_search, self.order_lookup, self.now = (
            llm, data_agent, policy_search, order_lookup, now)
        self.settings = get_settings()
        self.policy = load_policy()

    def handle(self, message: str, session: SessionState) -> TurnResult:
        start = time.perf_counter()
        trace: dict = {"steps": []}
        result = self._handle(message, session, trace)
        trace["seconds"] = round(time.perf_counter() - start, 2)
        session.history.append({"role": "assistant", "text": result.answer})
        result.trace = trace
        return result

    def _blocked(self, trace: dict, reason: str) -> TurnResult:
        trace["blocked"] = reason
        return TurnResult(self.policy.replies.blocked)

    def _handle(self, message: str, session: SessionState, trace: dict) -> TurnResult:
        checked = check_input(message, session, self.policy)
        trace["input_flags"] = checked.flags
        if not checked.allowed:
            trace["blocked"] = checked.flags[0]
            return TurnResult(checked.reply)
        text = checked.text
        history = _history_text(session, self.settings.history_turns)
        tags = Delimiter()

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                verdict_future = pool.submit(self.llm.structured, "guardrail", tags.system(prompts.GUARDRAIL),
                                             tags.block("message", text), GuardrailVerdict)
                parsed_future = pool.submit(self.llm.structured, "parser", tags.system(prompts.PARSER),
                                            tags.block("history", history) + "\n" + tags.block("message", text),
                                            ParsedRequest)
                verdict, verdict_call = verdict_future.result()
                parsed, parsed_call = parsed_future.result()
        except LLMUnavailable as error:
            trace["error"] = str(error)
            return TurnResult(self.policy.replies.unsupported_answer)
        trace["steps"] += [asdict(verdict_call), asdict(parsed_call)]
        trace["guardrail"] = verdict.model_dump()
        trace["parsed"] = parsed.model_dump()
        if verdict.suspicious:
            return self._blocked(trace, "llm_guardrail")

        rewritten = check_input(parsed.rewritten_question, session, self.policy)
        if not rewritten.allowed:
            return self._blocked(trace, "rewritten_question")
        question = rewritten.text
        session.history.append({"role": "customer", "text": text})

        capabilities = set().union(*(DISPATCH[intent] for intent in parsed.intents))
        trace["capabilities"] = sorted(capabilities)
        context: dict = {"flags": checked.flags}
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {}
                if "data" in capabilities:
                    futures["data"] = pool.submit(self.data_agent, self.llm, question)
                if "policies" in capabilities:
                    futures["policies"] = pool.submit(self.policy_search, question, 3)
                if "order" in capabilities:
                    futures["order"] = pool.submit(self._order_lookup, parsed, session)
                results = {name: future.result() for name, future in futures.items()}
        except LLMUnavailable as error:
            trace["error"] = str(error)
            return TurnResult(self.policy.replies.unsupported_answer)

        evidence: list = []
        retrieved_sections: list[str] = []
        if "data" in results:
            data = results["data"]
            context["catalog"] = {"summary": data.summary, "tool_results": data.tool_results}
            evidence.append(data.tool_results)
            trace["steps"].append(asdict(data.call))
            trace["tools"] = [{"tool": t["tool"], "args": t["args"]} for t in data.tool_results]
        if "policies" in results:
            sections = results["policies"]
            context["policies"] = [
                {"section": s["section_number"], "title": s["subsection"] or s["section"], "content": s["content"]}
                for s in sections
            ]
            retrieved_sections = [s["section_number"] for s in sections]
            evidence += [s["content"] for s in sections]
            trace["retrieved_sections"] = retrieved_sections
        if "order" in results:
            context["order"] = results["order"]
            evidence.append(results["order"])
            trace["order_status"] = results["order"]["status"]

        now = self.now()
        composer_input = "\n".join([
            f"Current date and time at the store: {now:%A %d/%m/%Y %H:%M}",
            tags.block("history", history),
            tags.block("question", question),
            tags.block("context", _json(context)),
        ])
        try:
            composed, composer_call = self.llm.structured("composer", tags.system(prompts.COMPOSER), composer_input,
                                                          ComposedAnswer)
        except LLMUnavailable as error:
            trace["error"] = str(error)
            return TurnResult(self.policy.replies.unsupported_answer)
        trace["steps"].append(asdict(composer_call))

        # 5. Deterministic output guardrail
        checked_output = check_output(composed.answer, evidence, composed.cited_sections, retrieved_sections,
                                      self.policy)
        trace["cited_sections"] = composed.cited_sections
        trace["output_violations"] = checked_output.violations
        return TurnResult(checked_output.answer)

    def _order_lookup(self, parsed: ParsedRequest, session: SessionState) -> dict:
        if parsed.order_id is None:
            return {"status": "needs_order_id"}
        # Grounding: the id must have been typed by the customer, not invented by the parser
        customer_text = " ".join(m["text"] for m in session.history if m["role"] == "customer")
        if not re.search(rf"(?<!\d){parsed.order_id}(?!\d)", customer_text):
            return {"status": "needs_order_id"}
        email, phone = session.latest("EMAIL"), session.latest("TEL")
        if not (email or phone):
            return {"status": "needs_credential", "order_id": parsed.order_id}
        if session.failed_order_lookups >= self.settings.max_failed_order_lookups:
            return {"status": "too_many_attempts"}
        order = self.order_lookup(parsed.order_id, email=email, phone=phone)
        if order is None:
            session.failed_order_lookups += 1
            return {"status": "not_found"}
        session.verified_orders.add(parsed.order_id)
        return {"status": "found", "order": order}