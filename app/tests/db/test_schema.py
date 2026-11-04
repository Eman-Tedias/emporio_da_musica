import psycopg
import pytest
from psycopg import errors
from psycopg.rows import dict_row

from app.config import get_settings
from app.ingest.csv_reader import load_tables
from app.ingest.db_loader import load_database
from app.tests.conftest import DATA_DIR

pytestmark = pytest.mark.integration

AUTHORIZED_ORDER_QUERY = "SELECT * FROM get_authorized_order(%s, %s, %s)"
# Order 1 belongs to customer 3 (Pedro Henrique Oliveira)
ORDER_1_EMAIL = "pedro.oliveira@jmail.com"
ORDER_1_PHONE = "67984321098"


@pytest.fixture(scope="module", autouse=True)
def loaded_database():
    if not DATA_DIR.exists():
        pytest.skip("data/ folder missing")
    try:
        load_database(get_settings().database_url_admin, load_tables(DATA_DIR))
    except psycopg.OperationalError:
        pytest.skip("database unavailable")


# Ingestion
def test_row_counts_match_csv(admin_conn, data_dir):
    tables = load_tables(data_dir)
    for name, rows in tables.items():
        total = admin_conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        assert total == len(rows), name

def test_ingestion_is_idempotent(admin_conn, data_dir):
    load_database(get_settings().database_url_admin, load_tables(data_dir))
    assert admin_conn.execute("SELECT count(*) FROM products").fetchone()[0] == \
        len(load_tables(data_dir)["products"])


# Constraints (as admin, undone by the fixture rollback)
@pytest.mark.parametrize("sql,error", [
    ("INSERT INTO products VALUES (999, 1, 'X', NULL, 10, 1, 'sold_out', NULL, NULL)", errors.CheckViolation),
    ("INSERT INTO products VALUES (999, 1, 'X', NULL, -1, 1, 'active', NULL, NULL)", errors.CheckViolation),
    ("INSERT INTO products VALUES (999, 99, 'X', NULL, 10, 1, 'active', NULL, NULL)", errors.ForeignKeyViolation),
    ("INSERT INTO customers VALUES (999, 'X', '1', '1', 'x@y.com', NULL)", errors.CheckViolation),
    ("INSERT INTO customers VALUES (999, 'X', '1', '67999999999', 'no-at-sign', NULL)", errors.CheckViolation),
    ("INSERT INTO orders VALUES (999, 1, '2026-01-01', 'lost', 10, 'pix', NULL, NULL, NULL)", errors.CheckViolation),
    ("INSERT INTO orders VALUES (999, 1, '2026-01-01', 'pending', 10, 'check', NULL, NULL, NULL)", errors.CheckViolation),
    ("INSERT INTO orders VALUES (999, 1, '2026-01-01', 'pending', 10, 'pix', 'XX1', NULL, NULL)", errors.CheckViolation),
    ("INSERT INTO order_items VALUES (1, 81, 0)", errors.CheckViolation),
])
def test_constraint_rejects_invalid_data(admin_conn, sql, error):
    with pytest.raises(error):
        admin_conn.execute(sql)


# Agent permissions
@pytest.mark.parametrize("table", ["categories", "products", "promotions"])
def test_agent_reads_catalog(agent_conn, table):
    assert agent_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0

@pytest.mark.parametrize("table", ["customers", "orders", "order_items"])
def test_agent_cannot_read_customer_data(agent_conn, table):
    with pytest.raises(errors.InsufficientPrivilege):
        agent_conn.execute(f"SELECT * FROM {table}")

@pytest.mark.parametrize("sql", [
    "INSERT INTO categories VALUES (99, 'X', NULL)",
    "UPDATE products SET price_brl = 0",
    "DELETE FROM promotions",
    "CREATE TABLE t (id int)",
])
def test_agent_cannot_write(agent_conn, sql):
    with pytest.raises(errors.InsufficientPrivilege):
        agent_conn.execute(sql)


# Authorized order lookup
def _get_order(conn, order_id, email=None, phone=None):
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(AUTHORIZED_ORDER_QUERY, (order_id, email, phone)).fetchall()

def test_correct_email_returns_order(agent_conn):
    rows = _get_order(agent_conn, 1, email=ORDER_1_EMAIL)
    assert len(rows) == 1
    assert rows[0]["status"] == "delivered"
    assert len(rows[0]["items"]) == 1

def test_email_is_case_insensitive(agent_conn):
    assert len(_get_order(agent_conn, 1, email=ORDER_1_EMAIL.upper())) == 1

def test_correct_phone_returns_order(agent_conn):
    assert len(_get_order(agent_conn, 1, phone=ORDER_1_PHONE)) == 1

def test_wrong_email_returns_nothing(agent_conn):
    assert _get_order(agent_conn, 1, email="someone.else@jmail.com") == []

def test_other_customer_credential_returns_nothing(agent_conn):
    # Order 2 belongs to customer 7, not customer 3
    assert _get_order(agent_conn, 2, email=ORDER_1_EMAIL) == []

def test_missing_credential_returns_nothing(agent_conn):
    assert _get_order(agent_conn, 1) == []

def test_unknown_order_returns_nothing(agent_conn):
    assert _get_order(agent_conn, 9999, email=ORDER_1_EMAIL) == []

def test_function_does_not_expose_customer_data(agent_conn):
    columns = set(_get_order(agent_conn, 1, email=ORDER_1_EMAIL)[0])
    assert columns.isdisjoint({"name", "email", "phone", "phone_digits", "customer_id"})
