from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

CENT = Decimal("0.01")

PIX_DISCOUNT_PERCENT = Decimal("5")

MAX_INSTALLMENTS = 12
INSTALLMENT_TIERS = [(3, Decimal("50")), (6, Decimal("80")), (12, Decimal("100"))]

METRO_CITIES = {"campo grande"}
METRO_FREE_SHIPPING_ABOVE = Decimal("500")
METRO_SHIPPING_FEE = Decimal("35")
METRO_DELIVERY_TIME = "1 to 3 business days"
OTHER_CITIES_DELIVERY_TIME = "PAC 5 to 12, SEDEX 2 to 5, Jadlog 3 to 8 business days"

ReturnReason = Literal["regret", "preference", "defect"]
RETURN_WINDOW_DAYS: dict[str, int] = {"regret": 7, "preference": 7, "defect": 30}


def to_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def apply_discount(price: Decimal, percent: Decimal) -> Decimal:
    return to_money(Decimal(price) * (100 - Decimal(percent)) / 100)


@dataclass(frozen=True)
class PriceQuote:
    list_price: Decimal
    final_price: Decimal
    discount_percent: Decimal
    discount_source: Literal["promotion", "pix", "none"]


def final_price(
    list_price: Decimal, payment_method: str, promotion_percents: list[Decimal] | None = None
) -> PriceQuote:
    """Promotions are not cumulative: the best active promotion wins and blocks the PIX discount."""
    list_price = to_money(list_price)
    if promotion_percents:
        best = max(Decimal(p) for p in promotion_percents)
        return PriceQuote(list_price, apply_discount(list_price, best), best, "promotion")
    if payment_method == "pix":
        return PriceQuote(
            list_price, apply_discount(list_price, PIX_DISCOUNT_PERCENT), PIX_DISCOUNT_PERCENT, "pix"
        )
    return PriceQuote(list_price, list_price, Decimal("0"), "none")


@dataclass(frozen=True)
class InstallmentPlan:
    installments: int
    installment_value: Decimal
    allowed: bool
    reason: str | None = None


def minimum_installment(installments: int) -> Decimal:
    if installments == 1:
        return Decimal("0")
    for max_count, minimum in INSTALLMENT_TIERS:
        if installments <= max_count:
            return minimum
    raise ValueError(f"installments must be between 1 and {MAX_INSTALLMENTS}")


def simulate_installments(total: Decimal, installments: int) -> InstallmentPlan:
    if not 1 <= installments <= MAX_INSTALLMENTS:
        return InstallmentPlan(
            installments, Decimal("0"), False, f"maximum is {MAX_INSTALLMENTS} installments"
        )
    value = to_money(Decimal(total) / installments)
    minimum = minimum_installment(installments)
    if value < minimum:
        return InstallmentPlan(
            installments, value, False,
            f"minimum installment for {installments}x is R$ {minimum:.2f}",
        )
    return InstallmentPlan(installments, value, True)


def max_installments(total: Decimal) -> int:
    allowed = [n for n in range(1, MAX_INSTALLMENTS + 1) if simulate_installments(total, n).allowed]
    return max(allowed)


def installment_options(total: Decimal) -> list[InstallmentPlan]:
    return [plan for n in range(1, MAX_INSTALLMENTS + 1) if (plan := simulate_installments(total, n)).allowed]


@dataclass(frozen=True)
class ShippingQuote:
    fee: Decimal | None
    delivery_time: str
    note: str | None = None


def shipping_quote(order_total: Decimal, city: str) -> ShippingQuote:
    if city.strip().lower() in METRO_CITIES:
        free = Decimal(order_total) > METRO_FREE_SHIPPING_ABOVE
        fee = Decimal("0") if free else METRO_SHIPPING_FEE
        return ShippingQuote(to_money(fee), METRO_DELIVERY_TIME, "delivered by the store courier")
    return ShippingQuote(
        None, OTHER_CITIES_DELIVERY_TIME,
        "fee is calculated from the destination ZIP code, weight and dimensions",
    )


@dataclass(frozen=True)
class ReturnEligibility:
    reason: str
    eligible: bool
    deadline: date
    days_left: int


def check_return_eligibility(reason: ReturnReason, reference_date: date, today: date) -> ReturnEligibility:
    """reference_date: delivery date for regret and preference, purchase date for defect."""
    deadline = reference_date + timedelta(days=RETURN_WINDOW_DAYS[reason])
    days_left = (deadline - today).days
    return ReturnEligibility(reason, days_left >= 0, deadline, max(days_left, 0))