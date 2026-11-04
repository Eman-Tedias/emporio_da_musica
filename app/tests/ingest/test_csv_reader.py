import csv

from app.ingest.csv_reader import detect_warnings, load_tables

TABLES = ["categories", "products", "promotions", "customers", "orders", "order_items"]


def count_csv_rows(data_dir, table):
    path = data_dir / f"desafio_tecnico_ai_eng - {table}.csv"
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def test_reads_all_tables(data_dir):
    assert set(load_tables(data_dir)) == set(TABLES)

def test_no_rows_lost(data_dir):
    tables = load_tables(data_dir)
    for name in TABLES:
        assert len(tables[name]) == count_csv_rows(data_dir, name), name

def test_warns_about_duplicated_email(data_dir):
    warnings = detect_warnings(load_tables(data_dir))
    assert any("bruno.martins@jmail.com" in w for w in warnings)
