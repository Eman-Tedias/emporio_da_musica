from datetime import date
from decimal import Decimal
import pytest

from app.tools.catalog import (
    get_product, list_active_promotions, list_categories, search_products,
)
from app.tools.orders import get_order

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def database(agent_conn):
    """Reuses the conftest fixture only to skip these tests when the database is down."""


def test_empty_categories_are_reported():
    counts = {c["name"]: c["available_products"] for c in list_categories()}
    assert counts["Cordas Orquestrais"] == 0
    assert counts["Violões"] > 0


def test_search_violoes_up_to_1000_without_accent():
    result = search_products(category="violoes", max_price=Decimal("1000"))
    assert result["category"] == "Violões"
    assert result["count"] > 0
    assert all(p["price_card"] <= Decimal("1000") for p in result["products"])
    assert all(p["availability"] == "in_stock" for p in result["products"])

def test_search_hides_out_of_stock_and_discontinued_by_default():
    names = [p["name"] for p in search_products(category="Violões", limit=20)["products"]]
    assert "Giannini GF-3D Dreadnought Sunburst" not in names
    assert "Shelby SN-7C 7 Cordas Nylon Natural" not in names

def test_unknown_category_lists_the_real_ones():
    result = search_products(category="amplificadores")
    assert "error" in result
    assert "Violões" in result["available_categories"]

def test_search_term_wildcards_are_escaped():
    assert search_products(term="Yamaha%C40")["count"] == 0
    assert search_products(term="Yamaha C40")["count"] == 1


@pytest.mark.parametrize("query,expected", [
    ("martin d28", "Martin D-28 Dreadnought Natural"),
    ("yamaha c40", "Yamaha C40 Nylon Natural"),
    ("violão takamine gd20", "Takamine GD20 Dreadnought Natural"),
])
def test_get_product_handles_punctuation_and_extra_words(query, expected):
    assert get_product(query)["product"]["name"] == expected

def test_promotion_lowers_the_effective_price():
    product = get_product("Kalani KAL-700T")["product"]
    assert product["active_promotion_percent"] == Decimal("10")
    assert product["price_card"] == Decimal("323.10")
    assert product["price_pix"] == Decimal("323.10")

def test_get_product_by_approximate_name():
    result = get_product("takamine gd20")
    assert result["found"]
    product = result["product"]
    assert product["name"] == "Takamine GD20 Dreadnought Natural"
    assert product["price_card"] == Decimal("2199.00")
    assert product["price_pix"] == Decimal("2089.05")
    assert product["max_installments"] == 12

def test_ambiguous_name_returns_candidates():
    result = get_product("yamaha")
    assert not result["found"]
    assert len(result["candidates"]) > 1

def test_unknown_product():
    assert not get_product("theremin quântico xyz")["found"]

def test_coming_soon_product_is_flagged():
    assert get_product("Kala KA-ABP-CTG")["product"]["availability"] == "coming_soon"


def test_active_promotions():
    assert len(list_active_promotions()) == 4


def test_order_with_correct_email():
    order = get_order(1, email="pedro.oliveira@jmail.com", today=date(2025, 10, 28))
    assert order["status"] == "delivered"
    assert order["return_eligibility"]["regret"]["eligible"]

def test_order_with_formatted_phone():
    assert get_order(1, phone="(67) 98432-1098") is not None

def test_order_with_wrong_credential():
    assert get_order(1, email="someone.else@jmail.com") is None

def test_return_window_expired():
    order = get_order(1, email="pedro.oliveira@jmail.com", today=date(2026, 11, 4))
    assert not order["return_eligibility"]["regret"]["eligible"]
    assert not order["return_eligibility"]["defect"]["eligible"]