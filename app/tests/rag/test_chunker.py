from pathlib import Path

import pytest

from app.rag.chunker import COVER_SECTION, Chunk, chunk_pages, chunk_pdf, split_into_pieces

PDF = Path("data/políticas_da_loja.pdf")

HEADER = "**Empório da Música** Manual de Políticas e Procedimentos"
PAGES = [
    (1, "# **EMPÓRIO DA MÚSICA**\nRua 14 de Maio, 3200\n"),
    (2, f"{HEADER}\n## **3. Formas de Pagamento**\nAceitamos:\n|PIX|à vista|\n"
        "### **3.1 Regras de Parcelamento**\nAté 3x sem juros.\nPágina 2\n"),
    (3, f"{HEADER}\nDe 4x a 6x: mínimo R$ 80.\n## **4. Trocas**\nEm até 7 dias.\nPágina 3\n"),
]


def test_cover_text_before_first_heading():
    chunks = chunk_pages(PAGES)
    assert chunks[0].section == COVER_SECTION
    assert "Rua 14 de Maio" in chunks[0].content

def test_one_chunk_per_section_and_subsection():
    titles = [c.title for c in chunk_pages(PAGES)]
    assert titles == [
        COVER_SECTION,
        "3. Formas de Pagamento",
        "3. Formas de Pagamento > 3.1 Regras de Parcelamento",
        "4. Trocas",
    ]

def test_section_numbers():
    assert [c.section_number for c in chunk_pages(PAGES)] == ["cover", "3", "3.1", "4"]

def test_tables_stay_inside_their_section():
    assert "|PIX|à vista|" in chunk_pages(PAGES)[1].content

def test_repeated_header_and_footer_are_removed_without_hardcoding():
    for chunk in chunk_pages(PAGES):
        assert "Página" not in chunk.content
        assert "Manual de Políticas" not in chunk.content

def test_short_documents_keep_all_lines():
    chunks = chunk_pages(PAGES[:2])
    assert any("Manual de Políticas" in c.content for c in chunks)

def test_subsection_spanning_two_pages():
    subsection = chunk_pages(PAGES)[2]
    assert subsection.pages == [2, 3]
    assert "mínimo R$ 80" in subsection.content

def test_embedding_text_includes_the_title():
    assert chunk_pages(PAGES)[2].text_for_embedding.startswith("3. Formas de Pagamento > 3.1")


TABLE_SECTION = Chunk(
    "3. Formas de Pagamento",
    content="Aceitamos:\n|Forma|Condições|\n|---|---|\n|PIX|à vista|\n|Boleto|3 dias|\n\n- Item um\n- Item dois",
)

def test_table_rows_keep_the_header():
    pieces = split_into_pieces(TABLE_SECTION)
    assert "|Forma|Condições|\n|PIX|à vista|" in pieces
    assert "|Forma|Condições|\n|Boleto|3 dias|" in pieces

def test_separator_row_is_not_a_piece():
    assert not any("---" in p for p in split_into_pieces(TABLE_SECTION))

def test_each_list_item_is_a_piece():
    pieces = split_into_pieces(TABLE_SECTION)
    assert "- Item um" in pieces and "- Item dois" in pieces

def test_pieces_carry_the_section_title():
    assert all(p.startswith("3. Formas de Pagamento\n") for p in TABLE_SECTION.pieces_for_embedding)


@pytest.fixture(scope="module")
def manual_chunks():
    if not PDF.exists():
        pytest.skip("policies PDF missing in data/")
    return chunk_pdf(PDF)

def test_real_manual_has_one_chunk_per_section(manual_chunks):
    assert len(manual_chunks) == 26

def test_real_manual_section_numbers_are_unique(manual_chunks):
    numbers = [c.section_number for c in manual_chunks]
    assert len(numbers) == len(set(numbers))

def test_real_manual_has_no_running_header(manual_chunks):
    assert not any("Página" in c.content for c in manual_chunks)

def test_real_manual_keeps_payment_table(manual_chunks):
    payment = next(c for c in manual_chunks if c.section_number == "3")
    assert "|Cartão de Crédito|Até 12x sem juros|" in payment.content

def test_real_manual_regret_rule(manual_chunks):
    regret = next(c for c in manual_chunks if c.section_number == "4.1")
    assert "7 (sete) dias" in regret.content