import psycopg
from psycopg.rows import dict_row

from app.config import get_settings


def agent_connection() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url_agent, row_factory=dict_row, connect_timeout=5)