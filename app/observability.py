import logging
from contextlib import contextmanager
from functools import lru_cache

from app.config import get_settings

NOISY_LOGGERS = ("httpx", "httpx2", "httpcore", "openai", "google_genai", "urllib3", "langfuse")


def configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


@lru_cache
def get_langfuse():
    settings = get_settings()
    if not (settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )


@contextmanager
def observe(name: str, as_type: str = "span", **attributes):
    client = get_langfuse()
    if client is None:
        yield None
        return
    with client.start_as_current_observation(name=name, as_type=as_type, **attributes) as observation:
        yield observation


def update(observation, **attributes) -> None:
    if observation is not None:
        observation.update(**attributes)


@contextmanager
def session_trace(session_id: str | None):
    if get_langfuse() is None or session_id is None:
        yield
        return
    from langfuse import propagate_attributes

    with propagate_attributes(session_id=session_id, trace_name="turn"):
        yield


def flush() -> None:
    client = get_langfuse()
    if client is not None:
        client.flush()
