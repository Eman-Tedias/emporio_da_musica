from decimal import Decimal

import pytest

from app.guardrails.output import check_output, evidence_numbers

PRODUCT = {"name": "Takamine GD20", "price_card": Decimal("2199.00"), "price_pix": Decimal("2089.05"),
           "max_installments": 12}
POLICY_TEXT = "Frete grátis para pedidos acima de R$ 500,00. Taxa fixa de R$ 35,00. PIX com 5% de desconto."


@pytest.mark.parametrize("answer", [
    "O Takamine GD20 sai por R$ 2.199,00 no cartão ou R$ 2.089,05 no PIX.",
    "Fica R$2199 no cartão.",
    "Acima de R$ 500,00 o frete é grátis, senão é R$ 35.",
    "No PIX você ganha 5% de desconto.",
    "Dá para parcelar em até 12x.",
])
def test_supported_values_pass(answer):
    assert check_output(answer, [PRODUCT, POLICY_TEXT]).allowed

@pytest.mark.parametrize("answer,violation", [
    ("Sai por R$ 1.999,00 no PIX.", "unsupported_money:1.999,00"),
    ("Hoje tem 50% de desconto!", "unsupported_percent:50"),
])
def test_invented_values_are_blocked(answer, violation):
    result = check_output(answer, [PRODUCT, POLICY_TEXT])
    assert not result.allowed and violation in result.violations
    assert "atendente" in result.answer

def test_answer_without_numbers_passes_without_evidence():
    assert check_output("Posso te ajudar com mais alguma coisa?", []).allowed


# Contacts and personal data
def test_store_contacts_are_allowed():
    answer = "Fale com a gente no (67) 3341-4444 ou contato@emporiodamusica.com.br."
    assert check_output(answer, []).allowed

def test_customer_email_is_blocked():
    assert "foreign_email" in check_output("O email do cliente é ana@jmail.com", []).violations

def test_customer_phone_is_blocked():
    assert "foreign_phone" in check_output("Ligue para (67) 99812-3456", []).violations

def test_cpf_is_blocked():
    assert "cpf" in check_output("CPF 529.982.247-25", []).violations


# Citations
def test_citation_of_retrieved_section_passes():
    assert check_output("Conforme a seção 4.1...", [], ["4.1"], ["4.1", "4.2"]).allowed

def test_citation_of_section_not_retrieved_is_blocked():
    result = check_output("Conforme a seção 8.1...", [], ["8.1"], ["4.1"])
    assert "uncited_section:8.1" in result.violations


def test_evidence_numbers_walks_nested_structures():
    numbers = evidence_numbers({"products": [{"price": Decimal("599.9")}], "note": "R$ 1.299,00"})
    assert {Decimal("599.90"), Decimal("1299.00")} <= numbers