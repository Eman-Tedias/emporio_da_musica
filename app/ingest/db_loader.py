from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _to_db_value(value):
    return Jsonb(value) if isinstance(value, dict) else value


def insert_rows(cursor: psycopg.Cursor, table: str, rows: list[BaseModel]) -> None:
    if not rows:
        return
    columns = list(rows[0].model_dump().keys())
    query = sql.SQL("INSERT INTO {table} ({columns}) VALUES ({values})").format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
        values=sql.SQL(", ").join(sql.Placeholder() * len(columns)),
    )
    cursor.executemany(
        query, [[_to_db_value(v) for v in row.model_dump().values()] for row in rows]
    )


def load_database(conninfo: str, tables: dict[str, list[BaseModel]]) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(conninfo, connect_timeout=5) as conn:
        with conn.cursor() as cursor:
            cursor.execute(schema)
            for table, rows in tables.items():
                insert_rows(cursor, table, rows)