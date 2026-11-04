from pathlib import Path

import psycopg
import pytest

from app.config import get_settings

DATA_DIR = Path("data")


def _connect(url: str) -> psycopg.Connection:
    try:
        return psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("database unavailable: run docker compose up -d")


@pytest.fixture
def admin_conn():
    conn = _connect(get_settings().database_url_admin)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def agent_conn():
    conn = _connect(get_settings().database_url_agent)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def data_dir() -> Path:
    if not DATA_DIR.exists():
        pytest.skip("data/ folder missing: copy the challenge files")
    return DATA_DIR
