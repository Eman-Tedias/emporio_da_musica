import csv
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.ingest.models import (
    CategoryRow, CustomerRow, OrderItemRow, OrderRow, ProductRow, PromotionRow
)

FILE_TEMPLATE = "desafio_tecnico_ai_eng - {table}.csv"

TABLE_MODELS: dict[str, type[BaseModel]] = {
    "categories": CategoryRow,
    "products": ProductRow,
    "promotions": PromotionRow,
    "customers": CustomerRow,
    "orders": OrderRow,
    "order_items": OrderItemRow,
}

def read_table(data_dir: Path, table: str, model: type[BaseModel]) -> list[BaseModel]:
    path = data_dir / FILE_TEMPLATE.format(table=table)
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for line_number, row in enumerate(reader, start=2):  # line 1 is the header
            try:
                rows.append(model(**row))
            except ValidationError as error:
                raise ValueError(f"{path.name}, line {line_number}: {error}") from error
    return rows


def load_tables(data_dir: Path) -> dict[str, list[BaseModel]]:
    return {table: read_table(data_dir, table, model) for table, model in TABLE_MODELS.items()}


def detect_warnings(tables: dict[str, list[BaseModel]]) -> list[str]:
    warnings = []

    email_counts = Counter(customer.email.lower() for customer in tables["customers"])
    for email, count in email_counts.items():
        if count > 1:
            ids = [c.customer_id for c in tables["customers"] if c.email.lower() == email]
            warnings.append(f"duplicated email {email} in customers {ids}")

    return warnings