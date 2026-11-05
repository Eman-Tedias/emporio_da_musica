import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

POLICY_FILE = Path(__file__).with_name("policies.yaml")


class Replies(BaseModel):
    blocked: str
    too_long: str
    unsupported_answer: str


class GuardrailPolicy(BaseModel):
    max_message_length: int
    injection_patterns: list[str]
    accessory_terms: list[str]
    store_phones: list[str]
    store_emails: list[str]
    replies: Replies

    @property
    def injection_regexes(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.injection_patterns]

    @property
    def accessory_regex(self) -> re.Pattern:
        terms = "|".join(map(re.escape, self.accessory_terms))
        return re.compile(rf"(?<!\d )\b({terms})\b")


@lru_cache
def load_policy(path: Path = POLICY_FILE) -> GuardrailPolicy:
    return GuardrailPolicy(**yaml.safe_load(path.read_text(encoding="utf-8")))


def fold(text: str) -> str:
    """Lowercase without accents, for pattern matching only."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()