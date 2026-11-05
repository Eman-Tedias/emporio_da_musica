import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.guardrails.input import CPF, EMAIL, PHONE, digits, is_valid_cpf
from app.guardrails.policy import GuardrailPolicy, load_policy

CENT = Decimal("0.01")
MONEY = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)")
PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


@dataclass
class OutputCheck:
    allowed: bool
    answer: str
    violations: list[str] = field(default_factory=list)


def to_decimal(raw: str) -> Decimal | None:
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation:
        return None


def evidence_numbers(evidence) -> set[Decimal]:
    found: set[Decimal] = set()
    if isinstance(evidence, dict):
        for value in evidence.values():
            found |= evidence_numbers(value)
    elif isinstance(evidence, (list, tuple, set)):
        for value in evidence:
            found |= evidence_numbers(value)
    elif isinstance(evidence, bool):
        pass
    elif isinstance(evidence, (int, float, Decimal)):
        found.add(Decimal(str(evidence)).quantize(CENT))
    elif isinstance(evidence, str):
        found |= {n for n in map(to_decimal, NUMBER.findall(evidence)) if n is not None}
    return found


def check_output(
    answer: str,
    evidence,
    cited_sections: list[str] | None = None,
    retrieved_sections: list[str] | None = None,
    policy: GuardrailPolicy | None = None,
) -> OutputCheck:
    policy = policy or load_policy()
    known = evidence_numbers(evidence)
    violations: list[str] = []

    for raw in MONEY.findall(answer):
        value = to_decimal(raw)
        if value is not None and value not in known:
            violations.append(f"unsupported_money:{raw}")
    for raw in PERCENT.findall(answer):
        value = to_decimal(raw)
        if value is not None and value not in known:
            violations.append(f"unsupported_percent:{raw}")

    for email in EMAIL.findall(answer):
        if email.lower() not in policy.store_emails:
            violations.append("foreign_email")
    for phone in PHONE.findall(answer):
        if digits(phone)[-10:] not in [p[-10:] for p in policy.store_phones]:
            violations.append("foreign_phone")
    if any(is_valid_cpf(m) for m in CPF.findall(answer)):
        violations.append("cpf")

    retrieved = set(retrieved_sections or [])
    for section in cited_sections or []:
        if section not in retrieved:
            violations.append(f"uncited_section:{section}")

    if violations:
        return OutputCheck(False, policy.replies.unsupported_answer, violations)
    return OutputCheck(True, answer)