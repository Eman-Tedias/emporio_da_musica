import contextvars
import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
from app.observability import observe, session_trace, update
from app.rag.retriever import search_policies
from app.tools.orders import get_order

logger = logging.getLogger("emporio.orchestrator")

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


def _submit(pool: ThreadPoolExecutor, fn, *args):
    # Each thread gets a copy of the current context, so its observations nest under the turn
    return pool.submit(contextvars.copy_context().run, fn, *args)


@contextmanager
def _stage(trace: dict, name: str, as_type: str = "span", **attributes):
    start = time.perf_counter()
    try:
        with observe(name, as_type=as_type, **attributes) as observation:
            yield observation
    finally:
        trace["timings"][name] = round(time.perf_counter() - start, 3)


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

    def handle(self, message: str, session: SessionState, session_id: str | None = None) -> TurnResult:
        start = time.perf_counter()
        trace: dict = {"steps": [], "timings": {}}
        with session_trace(session_id), observe("turn", as_type="agent") as turn:
            result = self._handle(message, session, trace)
            trace["seconds"] = round(time.perf_counter() - start, 2)
            trace["timings"]["total"] = trace["seconds"]
            trace["cost_usd"] = round(sum(s.get("cost_usd") or 0 for s in trace["steps"]), 6)
            update(turn, input=trace.get("masked_message"), output=result.answer,
                   metadata={"timings": trace["timings"], "blocked": trace.get("blocked"),
                             "intents": (trace.get("parsed") or {}).get("intents")})
        session.history.append({"role": "assistant", "text": result.answer})
        result.trace = trace
        self._log(trace, session_id)
        return result

    @staticmethod
    def _log(trace: dict, session_id: str | None) -> None:
        stages = " ".join(f"{name}={seconds}" for name, seconds in trace["timings"].items() if name != "total")
        logger.info("turn session=%s intents=%s total=%.2fs cost_usd=%.5f llm_calls=%d stages=[%s]",
                    (session_id or "-")[:8], (trace.get("parsed") or {}).get("intents"), trace["seconds"],
                    trace["cost_usd"], len(trace["steps"]), stages)
        if trace.get("blocked"):
            logger.warning("turn blocked session=%s reason=%s", (session_id or "-")[:8], trace["blocked"])
        if trace.get("output_violations"):
            logger.warning("output guardrail replaced the answer session=%s violations=%s",
                           (session_id or "-")[:8], trace["output_violations"])

    def _blocked(self, trace: dict, reason: str) -> TurnResult:
        trace["blocked"] = reason
        return TurnResult(self.policy.replies.blocked)

    def _handle(self, message: str, session: SessionState, trace: dict) -> TurnResult:
        with _stage(trace, "input_guardrail", as_type="guardrail") as stage:
            checked = check_input(message, session, self.policy)
            update(stage, output={"allowed": checked.allowed, "flags": checked.flags})
        trace["input_flags"] = checked.flags
        if not checked.allowed:
            trace["blocked"] = checked.flags[0]
            return TurnResult(checked.reply)
        text = checked.text
        trace["masked_message"] = text
        history = _history_text(session, self.settings.history_turns)
        tags = Delimiter()

        try:
            with _stage(trace, "guardrail_and_parser"), ThreadPoolExecutor(max_workers=2) as pool:
                verdict_future = _submit(pool, self.llm.structured, "guardrail", tags.system(prompts.GUARDRAIL),
                                         tags.block("message", text), GuardrailVerdict)
                parsed_future = _submit(pool, self.llm.structured, "parser", tags.system(prompts.PARSER),
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
                    futures["data"] = _submit(pool, self._run_data_agent, trace, question)
                if "policies" in capabilities:
                    futures["policies"] = _submit(pool, self._run_policy_search, trace, question)
                if "order" in capabilities:
                    futures["order"] = _submit(pool, self._run_order_lookup, trace, parsed, session)
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
            trace["tools"] = [{"tool": t["tool"], "args": t["args"], "seconds": t.get("seconds")}
                              for t in data.tool_results]
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
            with _stage(trace, "composer"):
                composed, composer_call = self.llm.structured("composer", tags.system(prompts.COMPOSER),
                                                              composer_input, ComposedAnswer)
        except LLMUnavailable as error:
            trace["error"] = str(error)
            return TurnResult(self.policy.replies.unsupported_answer)
        trace["steps"].append(asdict(composer_call))

        with _stage(trace, "output_guardrail", as_type="guardrail") as stage:
            checked_output = check_output(composed.answer, evidence, composed.cited_sections, retrieved_sections,
                                          self.policy)
            update(stage, output={"allowed": checked_output.allowed, "violations": checked_output.violations},
                   **({} if checked_output.allowed else {"level": "WARNING"}))
        trace["cited_sections"] = composed.cited_sections
        trace["output_violations"] = checked_output.violations
        return TurnResult(checked_output.answer)

    def _run_data_agent(self, trace: dict, question: str):
        with _stage(trace, "data_agent", as_type="agent", input=question):
            return self.data_agent(self.llm, question)

    def _run_policy_search(self, trace: dict, question: str) -> list[dict]:
        with _stage(trace, "policy_search", as_type="retriever", input=question) as stage:
            sections = self.policy_search(question, 3)
            update(stage, output=[s["section_number"] for s in sections])
            return sections

    def _run_order_lookup(self, trace: dict, parsed: ParsedRequest, session: SessionState) -> dict:
        with _stage(trace, "order_lookup", as_type="tool") as stage:
            result = self._order_lookup(parsed, session)
            update(stage, output={"status": result["status"]})
            return result

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
            logger.warning("order lookup limit reached order_id=%s", parsed.order_id)
            return {"status": "too_many_attempts"}
        order = self.order_lookup(parsed.order_id, email=email, phone=phone)
        if order is None:
            session.failed_order_lookups += 1
            return {"status": "not_found"}
        session.verified_orders.add(parsed.order_id)
        return {"status": "found", "order": order}
