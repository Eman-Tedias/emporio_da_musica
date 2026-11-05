from datetime import date
from decimal import Decimal

import pytest

from app.calculators.rules import (
    check_return_eligibility, final_price, max_installments, shipping_quote, simulate_installments,
)

D = Decimal

def test_pix_gets_five_percent_discount():
    quote = final_price(D("1000"), "pix")
    assert quote.final_price == D("950.00")
    assert quote.discount_source == "pix"

def test_card_pays_list_price():
    quote = final_price(D("1000"), "credit_3x")
    assert quote.final_price == D("1000.00")
    assert quote.discount_source == "none"

def test_promotion_is_applied():
    quote = final_price(D("1000"), "credit_3x", [D("20")])
    assert quote.final_price == D("800.00")
    assert quote.discount_source == "promotion"

def test_pix_does_not_stack_on_promotion():
    assert final_price(D("1000"), "pix", [D("20")]).final_price == D("800.00")

def test_best_promotion_wins_when_several_are_active():
    assert final_price(D("1000"), "debit", [D("10"), D("25")]).discount_percent == D("25")

def test_price_is_rounded_to_cents():
    assert final_price(D("599.90"), "pix").final_price == D("569.91")

@pytest.mark.parametrize("total,n,allowed", [
    (D("120"), 3, False),
    (D("150"), 3, True),
    (D("480"), 6, True),
    (D("479"), 6, False),
    (D("1200"), 12, True),
    (D("1199"), 12, False),
    (D("30"), 1, True),
])
def test_installment_minimums(total, n, allowed):
    assert simulate_installments(total, n).allowed is allowed

def test_more_than_twelve_installments_is_not_allowed():
    plan = simulate_installments(D("10000"), 13)
    assert not plan.allowed
    assert "12" in plan.reason

def test_installment_value():
    assert simulate_installments(D("599.90"), 3).installment_value == D("199.97")

@pytest.mark.parametrize("total,expected", [
    (D("2399"), 12), (D("1000"), 10), (D("500"), 6), (D("159.90"), 3), (D("90"), 1),
])
def test_max_installments(total, expected):
    assert max_installments(total) == expected


def test_metro_free_shipping_above_500():
    assert shipping_quote(D("500.01"), "Campo Grande").fee == D("0.00")

def test_metro_fee_at_or_below_500():
    assert shipping_quote(D("500"), "campo grande ").fee == D("35.00")

def test_other_city_has_no_fixed_fee():
    quote = shipping_quote(D("1000"), "Dourados")
    assert quote.fee is None
    assert "SEDEX" in quote.delivery_time


def test_regret_on_the_last_day_is_eligible():
    result = check_return_eligibility("regret", date(2026, 3, 1), date(2026, 3, 8))
    assert result.eligible and result.days_left == 0

def test_regret_after_seven_days_is_not_eligible():
    assert not check_return_eligibility("regret", date(2026, 3, 1), date(2026, 3, 9)).eligible

def test_defect_within_thirty_days():
    result = check_return_eligibility("defect", date(2026, 3, 1), date(2026, 3, 20))
    assert result.eligible and result.days_left == 11

def test_defect_after_thirty_days_is_not_eligible():
    assert not check_return_eligibility("defect", date(2026, 3, 1), date(2026, 4, 1)).eligible


def test_installment_options_list_only_allowed_plans():
    from app.calculators.rules import installment_options
    options = installment_options(D("500"))
    assert [plan.installments for plan in options] == [1, 2, 3, 4, 5, 6]
    assert options[-1].installment_value == D("83.33")
