import json

import pytest
from fastapi.testclient import TestClient

from app.agents.orchestrator import TurnResult
from app.api import main
from app.api.sessions import SessionStore


class FakeOrchestrator:
    def __init__(self):
        self.sessions = []

    def handle(self, message, session, session_id=None):
        self.sessions.append(session)
        session.add_credential("EMAIL", "real@jmail.com")
        return TurnResult(f"eco: {message}", {"parsed": {"rewritten_question": "[EMAIL_1]"}})


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake, sessions = FakeOrchestrator(), SessionStore(max_messages_per_minute=3, idle_ttl_seconds=3600)
    monkeypatch.setattr(main.get_settings(), "trace_file", str(tmp_path / "traces.jsonl"))
    main.app.dependency_overrides[main.get_orchestrator] = lambda: fake
    main.app.dependency_overrides[main.get_sessions] = lambda: sessions
    with TestClient(main.app) as test_client:
        test_client.fake = fake
        test_client.trace_file = tmp_path / "traces.jsonl"
        yield test_client
    main.app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}

def test_first_message_creates_a_session(client):
    body = client.post("/chat", json={"message": "oi"}).json()
    assert body["answer"] == "eco: oi" and len(body["session_id"]) > 10

def test_same_session_keeps_its_state(client):
    first = client.post("/chat", json={"message": "oi"}).json()
    client.post("/chat", json={"session_id": first["session_id"], "message": "tudo bem?"})
    assert client.fake.sessions[0] is client.fake.sessions[1]

def test_unknown_session_id_is_not_trusted(client):
    body = client.post("/chat", json={"session_id": "chosen-by-attacker", "message": "oi"}).json()
    assert body["session_id"] != "chosen-by-attacker"

def test_rate_limit_per_session(client):
    session_id = client.post("/chat", json={"message": "1"}).json()["session_id"]
    codes = [client.post("/chat", json={"session_id": session_id, "message": "x"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]

@pytest.mark.parametrize("payload", [{}, {"message": ""}, {"message": "a" * 4001}])
def test_invalid_payload_is_rejected(client, payload):
    assert client.post("/chat", json=payload).status_code == 422

def test_trace_is_written_without_credentials(client):
    client.post("/chat", json={"message": "meu email é real@jmail.com"})
    line = json.loads(client.trace_file.read_text(encoding="utf-8").splitlines()[0])
    assert line["parsed"]["rewritten_question"] == "[EMAIL_1]"
    assert "real@jmail.com" not in client.trace_file.read_text(encoding="utf-8")