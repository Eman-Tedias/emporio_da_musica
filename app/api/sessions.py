import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from app.guardrails.session import SessionState


@dataclass
class StoredSession:
    state: SessionState = field(default_factory=SessionState)
    recent_messages: deque = field(default_factory=deque)
    last_seen: float = field(default_factory=time.monotonic)


class SessionStore:
    def __init__(self, max_messages_per_minute: int, idle_ttl_seconds: int):
        self.max_messages_per_minute = max_messages_per_minute
        self.idle_ttl_seconds = idle_ttl_seconds
        self._sessions: dict[str, StoredSession] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str | None) -> tuple[str, StoredSession]:
        with self._lock:
            self._drop_idle()
            if session_id and session_id in self._sessions:
                stored = self._sessions[session_id]
            else:
                session_id = secrets.token_urlsafe(16)
                stored = self._sessions[session_id] = StoredSession()
            stored.last_seen = time.monotonic()
            return session_id, stored

    def allow(self, stored: StoredSession) -> bool:
        with self._lock:
            now = time.monotonic()
            while stored.recent_messages and now - stored.recent_messages[0] > 60:
                stored.recent_messages.popleft()
            if len(stored.recent_messages) >= self.max_messages_per_minute:
                return False
            stored.recent_messages.append(now)
            return True

    def _drop_idle(self) -> None:
        now = time.monotonic()
        for session_id in [s for s, v in self._sessions.items() if now - v.last_seen > self.idle_ttl_seconds]:
            del self._sessions[session_id]