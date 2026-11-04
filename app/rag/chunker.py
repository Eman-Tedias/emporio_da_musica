import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

COVER_SECTION = "Cover"

HEADING = re.compile(r"^(#{1,3})\s+\**(.+?)\**\s*$")
SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")

REPEATED_LINE_SHARE = 0.5
MIN_PAGES_TO_DETECT_REPEATS = 3


@dataclass
class Chunk:
    section: str
    subsection: str | None = None
    pages: list[int] = field(default_factory=list)
    content: str = ""

    @property
    def title(self) -> str:
        return f"{self.section} > {self.subsection}" if self.subsection else self.section

    @property
    def section_number(self) -> str:
        match = SECTION_NUMBER.match(self.subsection or self.section)
        return match.group(1) if match else "cover"

    @property
    def text_for_embedding(self) -> str:
        return f"{self.title}\n\n{self.content}"

    @property
    def pieces_for_embedding(self) -> list[str]:
        return [f"{self.title}\n{piece}" for piece in split_into_pieces(self)]


def _line_signature(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def repeated_lines(pages: list[tuple[int, str]]) -> set[str]:
    if len(pages) < MIN_PAGES_TO_DETECT_REPEATS:
        return set()
    counts = Counter()
    for _, markdown in pages:
        counts.update({_line_signature(line) for line in markdown.splitlines() if line.strip()})
    threshold = len(pages) * REPEATED_LINE_SHARE
    return {signature for signature, count in counts.items() if count >= threshold}


def chunk_pages(pages: list[tuple[int, str]]) -> list[Chunk]:
    noise = repeated_lines(pages)
    chunks: list[Chunk] = []
    current = Chunk(COVER_SECTION)
    section = COVER_SECTION

    for page_number, markdown in pages:
        for line in markdown.splitlines():
            if _line_signature(line) in noise:
                continue
            heading = HEADING.match(line)
            if heading and len(heading.group(1)) >= 2:
                if current.content.strip():
                    chunks.append(current)
                title = heading.group(2).strip()
                if len(heading.group(1)) == 2:
                    section = title
                    current = Chunk(section)
                else:
                    current = Chunk(section, subsection=title)
                continue
            if line.strip():
                if page_number not in current.pages:
                    current.pages.append(page_number)
                current.content += line.rstrip() + "\n"

    if current.content.strip():
        chunks.append(current)
    for chunk in chunks:
        chunk.content = re.sub(r"\n{3,}", "\n\n", chunk.content).strip()
    return chunks


def split_into_pieces(chunk: Chunk) -> list[str]:
    pieces: list[str] = []
    table_header = None
    for line in chunk.content.splitlines():
        stripped = line.strip()
        if not stripped:
            table_header = None
            continue
        if stripped.startswith("|"):
            if re.fullmatch(r"\|[\s\-:|]+\|", stripped):
                continue
            if table_header is None:
                table_header = stripped
                continue
            pieces.append(f"{table_header}\n{stripped}")
            continue
        table_header = None
        pieces.append(stripped)
    return pieces


def load_pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    import pymupdf4llm

    pages = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True, show_progress=False, use_ocr=False)
    return [(page["metadata"]["page_number"], page["text"]) for page in pages]


def chunk_pdf(pdf_path: Path) -> list[Chunk]:
    return chunk_pages(load_pdf_pages(pdf_path))