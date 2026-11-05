import json
import logging
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.agents.orchestrator import Orchestrator
from app.api.sessions import SessionStore
from app.config import get_settings
from app.llm.client import get_llm_client

logger = logging.getLogger("emporio.api")
_trace_lock = threading.Lock()


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    trace: dict


@lru_cache
def get_orchestrator() -> Orchestrator:
    return Orchestrator(get_llm_client())


@lru_cache
def get_sessions() -> SessionStore:
    settings = get_settings()
    return SessionStore(settings.max_messages_per_minute, settings.session_idle_ttl_seconds)


def write_trace(session_id: str, trace: dict) -> None:
    """Traces only hold masked text: credentials stay in the session, never in logs."""
    path = Path(get_settings().trace_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": datetime.now(timezone.utc).isoformat(), "session_id": session_id, **trace},
                      ensure_ascii=False, default=str)
    with _trace_lock, path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


app = FastAPI(title="Empório da Música - atendimento")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    sessions: SessionStore = Depends(get_sessions),
) -> ChatResponse:
    session_id, stored = sessions.get_or_create(request.session_id)
    if not sessions.allow(stored):
        raise HTTPException(status_code=429, detail="Muitas mensagens em pouco tempo. Aguarde um minuto.")
    result = orchestrator.handle(request.message, stored.state)
    try:
        write_trace(session_id, result.trace)
    except OSError:
        logger.exception("could not write trace")
    return ChatResponse(session_id=session_id, answer=result.answer, trace=result.trace)