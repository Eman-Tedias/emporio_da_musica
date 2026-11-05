from dataclasses import dataclass, field


@dataclass
class SessionState:

    credentials: dict[str, str] = field(default_factory=dict)
    verified_orders: set[int] = field(default_factory=set)
    failed_order_lookups: int = 0
    history: list[dict] = field(default_factory=list)
    
    def add_credential(self, kind: str, value: str) -> str:
        for token, existing in self.credentials.items():
            if existing == value:
                return token
        count = sum(1 for token in self.credentials if token.startswith(f"{kind}_"))
        token = f"{kind}_{count + 1}"
        self.credentials[token] = value
        return token

    def credential(self, token: str) -> str | None:
        return self.credentials.get(token.strip("[]"))

    def latest(self, kind: str) -> str | None:
        tokens = [t for t in self.credentials if t.startswith(f"{kind}_")]
        return self.credentials[tokens[-1]] if tokens else None