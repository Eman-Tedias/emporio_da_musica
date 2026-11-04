from app.config import get_settings
from app.ingest.csv_reader import detect_warnings, load_tables
from app.ingest.db_loader import load_database


def main() -> None:
    settings = get_settings()
    tables = load_tables(settings.data_dir)

    for warning in detect_warnings(tables):
        print(f"WARNING: {warning}")

    load_database(settings.database_url_admin, tables)

    for table, rows in tables.items():
        print(f"{table}: {len(rows)} rows loaded")


if __name__ == "__main__":
    main()