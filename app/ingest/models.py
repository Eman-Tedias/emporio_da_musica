import json
import re
from datetime import date
from decimal import Decimal
from typing import Literal, Annotated

from pydantic import BaseModel, Field, computed_field, field_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PAYMENT_METHOD_PATTERN = r"^(pix|debit|boleto|credit_[0-9]{1,2}x)$"
TRACKING_CODE_PATTERN = r"^BR[A-Z0-9]{9}BR$"

class CategoryRow(BaseModel):
    category_id: int
    name: str
    description: str | None = None

class ProductRow(BaseModel):
    product_id: int
    category_id: int
    name: str
    description: str | None = None
    price_brl: Decimal = Field(ge=0, decimal_places=2)
    stock_quantity: int = Field(ge=0)
    status: Literal["active", "discontinued", "coming_soon"]
    specs: dict | None = None
    created_at: date | None = None

    @field_validator("specs", mode="before")
    @classmethod
    def parse_specs(cls, value):
        if value in ("", None):
            return None
        return json.loads(value)

class PromotionRow(BaseModel):
    promotion_id: int
    product_id: int
    discount_percent: Decimal = Field(gt=0, le=100)
    description: str | None = None
    is_active: bool

class CustomerRow(BaseModel):
    customer_id: int
    name: str
    phone: str
    email: str = Field(pattern=EMAIL_PATTERN)
    city: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        digits = re.sub(r"\D", "", value)
        if len(digits) not in (10, 11):
            raise ValueError("phone must have 10 or 11 digits")
        return value

    @computed_field
    @property
    def phone_digits(self) -> str:
        return re.sub(r"\D", "", self.phone)

class OrderRow(BaseModel):
    order_id: int
    customer_id: int
    order_date: date
    status: Literal["pending", "confirmed", "shipped", "delivered", "cancelled"]
    total_brl: Decimal = Field(ge=0, decimal_places=2)
    payment_method: str = Field(pattern=PAYMENT_METHOD_PATTERN)
    tracking_code: Annotated[str, Field(pattern=TRACKING_CODE_PATTERN)] | None = None
    estimated_delivery: date | None = None
    notes: str | None = None

    @field_validator("tracking_code", "estimated_delivery", "notes", mode="before")
    @classmethod
    def empty_to_none(cls, value):
        return None if value == "" else value

class OrderItemRow(BaseModel):
    order_id: int
    product_id: int
    quantity: int = Field(gt=0)