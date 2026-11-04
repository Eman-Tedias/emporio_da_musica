import psycopg

from app.config import get_settings
from app.rag.chunker import Chunk, chunk_pdf
from app.rag.embeddings import embed_texts, to_pgvector

POLICIES_FILE = "políticas_da_loja.pdf"

SCHEMA = """
DROP TABLE IF EXISTS policy_pieces, policy_sections;
CREATE TABLE policy_sections (
    section_number  TEXT PRIMARY KEY,
    section         TEXT NOT NULL,
    subsection      TEXT,
    pages           INT[] NOT NULL,
    content         TEXT NOT NULL
);
CREATE TABLE policy_pieces (
    piece_id        SERIAL PRIMARY KEY,
    section_number  TEXT NOT NULL REFERENCES policy_sections(section_number),
    text            TEXT NOT NULL,
    embedding       vector({dimensions}) NOT NULL
);
"""


def load_policies(conninfo: str, chunks: list[Chunk], piece_embeddings: list[list[float]]) -> int:
    pieces = [(c.section_number, text) for c in chunks for text in c.pieces_for_embedding]
    with psycopg.connect(conninfo, connect_timeout=5) as conn:
        conn.execute(SCHEMA.format(dimensions=len(piece_embeddings[0])))
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO policy_sections (section_number, section, subsection, pages, content)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(c.section_number, c.section, c.subsection, c.pages, c.content) for c in chunks],
            )
            cursor.executemany(
                "INSERT INTO policy_pieces (section_number, text, embedding) VALUES (%s, %s, %s::vector)",
                [(number, text, to_pgvector(e)) for (number, text), e in zip(pieces, piece_embeddings)],
            )
    return len(pieces)


def main() -> None:
    settings = get_settings()
    chunks = chunk_pdf(settings.data_dir / POLICIES_FILE)
    piece_texts = [text for c in chunks for text in c.pieces_for_embedding]
    total = load_policies(settings.database_url_admin, chunks, embed_texts(piece_texts))
    for chunk in chunks:
        print(f"{chunk.title} (pages {chunk.pages}, {len(chunk.pieces_for_embedding)} pieces)")
    print(f"{len(chunks)} sections and {total} pieces loaded")


if __name__ == "__main__":
    main()