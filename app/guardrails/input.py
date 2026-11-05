import re
import unicodedata
from dataclasses import dataclass, field

from app.guardrails.policy import GuardrailPolicy, fold, load_policy
from app.guardrails.session import SessionState

INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MARKUP = re.compile(r"</?\s*[A-Za-z][\w:-]*(?:\s[^<>]*)?/?\s*>")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}(?!\d)")
CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


@dataclass
class InputCheck:
    allowed: bool
    text: str
    flags: list[str] = field(default_factory=list)
    reply: str | None = None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = INVISIBLE.sub("", text)
    text = CONTROL.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def is_valid_cpf(value: str) -> bool:
    numbers = [int(d) for d in digits(value)]
    if len(numbers) != 11 or len(set(numbers)) == 1:
        return False
    for position in (9, 10):
        total = sum(n * (position + 1 - i) for i, n in enumerate(numbers[:position]))
        if (total * 10 % 11) % 10 != numbers[position]:
            return False
    return True


def is_valid_card(value: str) -> bool:
    numbers = [int(d) for d in digits(value)][::-1]
    if not 13 <= len(numbers) <= 19:
        return False
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(numbers))
    return total % 10 == 0


def check_input(message: str, session: SessionState, policy: GuardrailPolicy | None = None) -> InputCheck:
    policy = policy or load_policy()
    text = normalize(message)
    flags: list[str] = []

    if len(text) > policy.max_message_length:
        return InputCheck(False, "", ["too_long"], policy.replies.too_long)

    folded = fold(text)
    if any(regex.search(folded) for regex in policy.injection_regexes):
        return InputCheck(False, "", ["prompt_injection"], policy.replies.blocked)

    if MARKUP.search(text):
                text = re.sub(r" {2,}", " ", MARKUP.sub(" ", text)).strip()
                flags.append("markup_removed")

    def mask_card(match: re.Match) -> str:
        if is_valid_card(match.group()):
            flags.append("card_masked")
            return "[CARTAO]"
        return match.group()

    def mask_cpf(match: re.Match) -> str:
        if is_valid_cpf(match.group()):
            flags.append("cpf_masked")
            return "[CPF]"
        return match.group()

    text = CARD.sub(mask_card, text)
    text = CPF.sub(mask_cpf, text)
    text = EMAIL.sub(lambda m: f"[{session.add_credential('EMAIL', m.group().lower())}]", text)
    text = PHONE.sub(lambda m: f"[{session.add_credential('TEL', digits(m.group())[-11:])}]", text)

    if policy.accessory_regex.search(fold(text)):
        flags.append("accessory_mention")
    return InputCheck(True, text, flags)
