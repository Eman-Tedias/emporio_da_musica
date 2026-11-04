from app.rag.embeddings import embed_query, to_pgvector
from app.tools.db import agent_connection

CANDIDATE_PIECES = 30

SEARCH_QUERY = """
    WITH ranked_pieces AS (
        SELECT section_number, 1 - (embedding <=> %(embedding)s::vector) AS similarity
          FROM policy_pieces
         ORDER BY embedding <=> %(embedding)s::vector
         LIMIT %(candidates)s
    ), best_per_section AS (
        SELECT section_number, max(similarity) AS similarity
          FROM ranked_pieces
         GROUP BY section_number
    )
    SELECT s.section_number, s.section, s.subsection, s.pages, s.content, b.similarity
      FROM best_per_section b
      JOIN policy_sections s USING (section_number)
     ORDER BY b.similarity DESC
     LIMIT %(top_k)s
"""


def search_policies(question: str, top_k: int = 3, embedding: list[float] | None = None) -> list[dict]:
    embedding = embedding or embed_query(question)
    with agent_connection() as conn:
        return conn.execute(SEARCH_QUERY, {
            "embedding": to_pgvector(embedding), "candidates": CANDIDATE_PIECES, "top_k": top_k,
        }).fetchall()