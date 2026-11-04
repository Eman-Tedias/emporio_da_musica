import pytest

from app.rag.retriever import search_policies

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def database(agent_conn):
    """Skip function"""


@pytest.mark.parametrize("question,expected_section", [
    ("me arrependi da compra, posso devolver?", "4.1"),
    ("qual o horário de funcionamento no sábado?", "2"),
    ("quanto tempo demora a entrega por SEDEX?", "5.2"),
    ("vocês aceitam boleto?", "3"),
])
def test_expected_section_in_top_3(question, expected_section):
    numbers = [r["section_number"] for r in search_policies(question, top_k=3)]
    assert expected_section in numbers, numbers

def test_each_section_is_returned_once():
    numbers = [r["section_number"] for r in search_policies("formas de pagamento e parcelamento", top_k=5)]
    assert len(numbers) == len(set(numbers))

def test_results_come_with_section_content_and_pages():
    result = search_policies("qual o endereço da loja?", top_k=1)[0]
    assert result["content"] and result["pages"]