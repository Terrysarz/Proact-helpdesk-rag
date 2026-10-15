"""
Ingest-stap: documenten inlezen -> opdelen in chunks -> embeddings maken ->
opslaan als vector-index (index.json).

Draai dit één keer (en opnieuw na het wijzigen van documenten):
    python src/ingest.py
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from config import DOCS_DIR, INDEX_PATH, CHUNK_SIZE, CHUNK_OVERLAP
from lmclient import embed


def read_documents(docs_dir: Path) -> list[tuple[str, str]]:
    """Leest alle .md- en .txt-bestanden in. Geeft (bestandsnaam, inhoud) terug."""
    docs = []
    for path in sorted(docs_dir.glob("*")):
        if path.suffix.lower() in (".md", ".txt"):
            docs.append((path.name, path.read_text(encoding="utf-8")))
    return docs


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """
    Verdeelt tekst in overlappende chunks van ~`size` tekens.

    We knippen bij voorkeur op een alinea-grens (dubbele newline) binnen het
    venster, zodat een chunk niet midden in een zin eindigt. Lukt dat niet, dan
    knippen we hard op `size`.
    """
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # Probeer netjes op een alinea-grens af te breken.
        if end < len(text):
            break_point = text.rfind("\n\n", start, end)
            if break_point > start + size // 2:
                end = break_point
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_index() -> None:
    """Hoofdfunctie: bouwt de volledige vector-index en schrijft index.json."""
    docs = read_documents(DOCS_DIR)
    if not docs:
        print(f"Geen documenten gevonden in {DOCS_DIR}. Zet er .md/.txt in.")
        sys.exit(1)

    records = []
    for filename, content in docs:
        chunks = chunk_text(content, CHUNK_SIZE, CHUNK_OVERLAP)
        print(f"  {filename}: {len(chunks)} chunk(s)")
        for i, chunk in enumerate(chunks):
            vector = embed(chunk)
            records.append({
                "source": filename,
                "chunk_id": i,
                "text": chunk,
                "embedding": vector,
            })

    INDEX_PATH.write_text(
        json.dumps(records, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nKlaar. {len(records)} chunks geïndexeerd -> {INDEX_PATH.name}")


if __name__ == "__main__":
    print(f"Documenten inlezen uit: {DOCS_DIR}")
    build_index()
