from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ingest.models import (
    CategoryRow, CustomerRow, OrderItemRow, OrderRow, ProductRow, PromotionRow,
)

CATEGORY = {"category_id": "1", "name": "Guitarras", "description": "Guitarras elétricas"}
PRODUCT = {
    "product_id": "81", "price_brl": "599.9", "name": "Yamaha C40 Nylon Natural",
    "category_id": "5", "description": "Violão clássico", "stock_quantity": "12",
    "status": "active", "specs": '{"top":"Spruce","strings":"nylon"}', "created_at": "2021-03-15",
}
PROMOTION = {"promotion_id": "1", "product_id": "102", "discount_percent": "10",
             "description": "Black Friday", "is_active": "0"}
CUSTOMER = {"customer_id": "1", "name": "Lucas Mendes da Silva", "phone": "(67) 99812-3456",
            "email": "lucas.mendes@jmail.com", "city": "Campo Grande"}
ORDER = {"order_id": "9", "customer_id": "6", "order_date": "2026-02-20", "status": "confirmed",
         "total_brl": "349.9", "payment_method": "credit_6x", "tracking_code": "",
         "estimated_delivery": "", "notes": ""}
ITEM = {"order_id": "1", "quantity": "1", "product_id": "93"}


def with_(base: dict, **changes) -> dict:
    return {**base, **changes}


# Category
def test_valid_category():
    assert CategoryRow(**CATEGORY).category_id == 1


# Product
def test_price_becomes_decimal():
    assert ProductRow(**PRODUCT).price_brl == Decimal("599.90")

def test_specs_becomes_dict():
    assert ProductRow(**PRODUCT).specs == {"top": "Spruce", "strings": "nylon"}

def test_created_at_becomes_date():
    assert ProductRow(**PRODUCT).created_at == date(2021, 3, 15)

@pytest.mark.parametrize("status", ["active", "discontinued", "coming_soon"])
def test_valid_statuses(status):
    assert ProductRow(**with_(PRODUCT, status=status)).status == status

def test_invalid_status_fails():
    with pytest.raises(ValidationError):
        ProductRow(**with_(PRODUCT, status="sold_out"))

@pytest.mark.parametrize("field,value", [("price_brl", "-1"), ("stock_quantity", "-1")])
def test_negative_values_fail(field, value):
    with pytest.raises(ValidationError):
        ProductRow(**with_(PRODUCT, **{field: value}))

def test_invalid_specs_json_fails():
    with pytest.raises(ValidationError):
        ProductRow(**with_(PRODUCT, specs="{broken"))


# Promotion
@pytest.mark.parametrize("raw,expected", [("0", False), ("1", True)])
def test_is_active_becomes_bool(raw, expected):
    assert PromotionRow(**with_(PROMOTION, is_active=raw)).is_active is expected

@pytest.mark.parametrize("discount", ["0", "101", "-5"])
def test_discount_out_of_range_fails(discount):
    with pytest.raises(ValidationError):
        PromotionRow(**with_(PROMOTION, discount_percent=discount))


# Customer
def test_phone_digits_keeps_only_numbers():
    assert CustomerRow(**CUSTOMER).phone_digits == "67998123456"

def test_original_phone_is_preserved():
    assert CustomerRow(**CUSTOMER).phone == "(67) 99812-3456"

def test_invalid_email_fails():
    with pytest.raises(ValidationError):
        CustomerRow(**with_(CUSTOMER, email="lucas.jmail.com"))

def test_phone_with_too_few_digits_fails():
    with pytest.raises(ValidationError):
        CustomerRow(**with_(CUSTOMER, phone="(67) 9981"))


# Order
@pytest.mark.parametrize("field", ["tracking_code", "estimated_delivery", "notes"])
def test_empty_field_becomes_none(field):
    assert getattr(OrderRow(**ORDER), field) is None

def test_total_becomes_decimal():
    assert OrderRow(**ORDER).total_brl == Decimal("349.90")

@pytest.mark.parametrize("method", ["pix", "debit", "boleto", "credit_3x", "credit_12x"])
def test_valid_payment_methods(method):
    assert OrderRow(**with_(ORDER, payment_method=method)).payment_method == method

@pytest.mark.parametrize("method", ["check", "credit_x", "credit_123x"])
def test_invalid_payment_method_fails(method):
    with pytest.raises(ValidationError):
        OrderRow(**with_(ORDER, payment_method=method))

def test_invalid_order_status_fails():
    with pytest.raises(ValidationError):
        OrderRow(**with_(ORDER, status="lost"))

def test_malformed_tracking_code_fails():
    with pytest.raises(ValidationError):
        OrderRow(**with_(ORDER, tracking_code="XX123"))


# Order item
def test_zero_quantity_fails():
    with pytest.raises(ValidationError):
        OrderItemRow(**with_(ITEM, quantity="0"))
