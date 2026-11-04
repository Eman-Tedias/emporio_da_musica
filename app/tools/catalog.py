import re
import unicodedata
from decimal import Decimal

from rapidfuzz import fuzz, process

from app.calculators.rules import final_price, max_installments
from app.tools.db import agent_connection

CATEGORY_MATCH_CUTOFF = 75
PRODUCT_MATCH_CUTOFF = 50
PRODUCT_CONFIDENT_SCORE = 90
PRODUCT_AMBIGUITY_MARGIN = 10

QUERY_STOPWORDS = {
    "o", "a", "os", "as", "um", "uma", "de", "do", "da", "modelo",
    "violao", "violoes", "guitarra", "guitarras", "baixo", "baixos", "ukulele", "ukuleles",
    "teclado", "teclados", "instrumento", "instrumentos",
}

EFFECTIVE_PRICE = (
    "p.price_brl * (100 - COALESCE(max(pr.discount_percent) FILTER (WHERE pr.is_active), 0)) / 100"
)

PRODUCT_SELECT = """
    SELECT p.product_id, p.name, c.name AS category, p.description, p.specs,
           p.price_brl, p.stock_quantity, p.status,
           COALESCE(array_agg(pr.discount_percent) FILTER (WHERE pr.is_active), '{}') AS active_discounts
      FROM products p
      JOIN categories c ON c.category_id = p.category_id
      LEFT JOIN promotions pr ON pr.product_id = p.product_id
"""


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9 ]", "", without_accents).strip()


def availability(status: str, stock_quantity: int) -> str:
    if status in ("discontinued", "coming_soon"):
        return status
    return "in_stock" if stock_quantity > 0 else "out_of_stock"


def summarize(row: dict, detailed: bool = False) -> dict:
    discounts = [Decimal(d) for d in row["active_discounts"]]
    card = final_price(row["price_brl"], "credit", discounts)
    pix = final_price(row["price_brl"], "pix", discounts)
    summary = {
        "product_id": row["product_id"],
        "name": row["name"],
        "category": row["category"],
        "availability": availability(row["status"], row["stock_quantity"]),
        "list_price": card.list_price,
        "active_promotion_percent": max(discounts) if discounts else None,
        "price_card": card.final_price,
        "price_pix": pix.final_price,
        "max_installments": max_installments(card.final_price),
    }
    if detailed:
        summary["description"] = row["description"]
        summary["specs"] = row["specs"]
    return summary


def list_categories() -> list[dict]:
    with agent_connection() as conn:
        return conn.execute("""
            SELECT c.name,
                   count(p.product_id) FILTER (
                       WHERE p.status = 'active' AND p.stock_quantity > 0
                   ) AS available_products
              FROM categories c
              LEFT JOIN products p ON p.category_id = c.category_id
             GROUP BY c.category_id
             ORDER BY c.category_id
        """).fetchall()


def resolve_category(name: str) -> dict | None:
    with agent_connection() as conn:
        categories = conn.execute("SELECT category_id, name FROM categories").fetchall()
    choices = {c["category_id"]: c["name"] for c in categories}
    match = process.extractOne(
        name, choices, scorer=fuzz.WRatio, processor=normalize, score_cutoff=CATEGORY_MATCH_CUTOFF
    )
    if match is None:
        return None
    category_name, _, category_id = match
    return {"category_id": category_id, "name": category_name}


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_products(
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    term: str | None = None,
    only_available: bool = True,
    limit: int = 10,
) -> dict:
    category_id = None
    resolved_category = None
    if category:
        resolved = resolve_category(category)
        if resolved is None:
            return {
                "error": f"unknown category: {category}",
                "available_categories": [c["name"] for c in list_categories()],
            }
        category_id, resolved_category = resolved["category_id"], resolved["name"]

    params = {
        "category_id": category_id,
        "min_price": min_price,
        "max_price": max_price,
        "term": f"%{_escape_like(term)}%" if term else None,
        "only_available": only_available,
        "limit": max(1, min(limit, 20)),
    }
    query = PRODUCT_SELECT + f"""
     WHERE (%(category_id)s::int IS NULL OR p.category_id = %(category_id)s::int)
       AND (%(term)s::text IS NULL OR p.name ILIKE %(term)s::text OR p.description ILIKE %(term)s::text)
       AND (NOT %(only_available)s::boolean OR (p.status = 'active' AND p.stock_quantity > 0))
     GROUP BY p.product_id, c.name
    HAVING (%(min_price)s::numeric IS NULL OR {EFFECTIVE_PRICE} >= %(min_price)s::numeric)
       AND (%(max_price)s::numeric IS NULL OR {EFFECTIVE_PRICE} <= %(max_price)s::numeric)
     ORDER BY {EFFECTIVE_PRICE}
     LIMIT %(limit)s
    """
    with agent_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return {
        "category": resolved_category,
        "count": len(rows),
        "products": [summarize(row) for row in rows],
    }


def get_product(name: str) -> dict:
    words = normalize(name).split()
    query = " ".join(w for w in words if w not in QUERY_STOPWORDS) or " ".join(words)
    with agent_connection() as conn:
        products = conn.execute("SELECT product_id, name FROM products").fetchall()
        choices = {p["product_id"]: normalize(p["name"]) for p in products}
        names = {p["product_id"]: p["name"] for p in products}
        matches = process.extract(
            query, choices, scorer=fuzz.token_set_ratio,
            score_cutoff=PRODUCT_MATCH_CUTOFF, limit=5,
        )
        if not matches:
            return {"found": False, "query": name}

        _, best_score, best_id = matches[0]
        runner_up_score = matches[1][1] if len(matches) > 1 else 0
        if best_score < PRODUCT_CONFIDENT_SCORE or best_score - runner_up_score < PRODUCT_AMBIGUITY_MARGIN:
            return {"found": False, "query": name, "candidates": [names[m[2]] for m in matches]}

        row = conn.execute(
            PRODUCT_SELECT + " WHERE p.product_id = %s GROUP BY p.product_id, c.name", (best_id,)
        ).fetchone()
    return {"found": True, "product": summarize(row, detailed=True)}


def list_active_promotions() -> list[dict]:
    with agent_connection() as conn:
        rows = conn.execute(
            PRODUCT_SELECT + """
             GROUP BY p.product_id, c.name
            HAVING bool_or(pr.is_active)
             ORDER BY p.name
            """
        ).fetchall()
    return [summarize(row) for row in rows]