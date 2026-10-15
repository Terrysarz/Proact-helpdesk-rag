"""
RAG-kern: haalt de meest relevante chunks op bij een vraag, bouwt een prompt
met die context en laat het LLM antwoorden. Geeft ook de gebruikte bronnen terug.

Wordt gebruikt door zowel cli.py als app.py.
"""

from __future__ import annotations
import json
from functools import lru_cache

from config import INDEX_PATH, TOP_K, MIN_SCORE, SYSTEM_PROMPT
from lmclient import embed, cosine_similarity, ask_llm


@lru_cache(maxsize=1)
def load_index() -> list[dict]:
    """Laadt de vector-index één keer in het geheugen (gecachet)."""
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"{INDEX_PATH.name} niet gevonden. Draai eerst: python src/ingest.py"
        )
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def retrieve(question: str, top_k: int = TOP_K) -> list[dict]:
    """Zoekt de top-k chunks met de hoogste similarity t.o.v. de vraag."""
    index = load_index()
    q_vec = embed(question)

    scored = []
    for record in index:
        score = cosine_similarity(q_vec, record["embedding"])
        scored.append((score, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = []
    for score, record in scored[:top_k]:
        results.append({
            "score": round(score, 3),
            "source": record["source"],
            "text": record["text"],
        })
    return results


def build_context(hits: list[dict]) -> str:
    """Zet de gevonden chunks om in een genummerd context-blok voor de prompt."""
    blocks = []
    for n, hit in enumerate(hits, start=1):
        blocks.append(f"[Bron {n}: {hit['source']}]\n{hit['text']}")
    return "\n\n".join(blocks)


def answer(question: str) -> dict:
    """
    Volledige RAG-flow: retrieve -> context bouwen -> LLM laten antwoorden.

    Geeft een dict terug met het antwoord en de gebruikte bronnen, zodat de
    UI die netjes kan tonen.
    """
    hits = retrieve(question)

    # Niets relevants gevonden -> niet gokken, eerlijk terugmelden.
    if not hits or hits[0]["score"] < MIN_SCORE:
        return {
            "answer": "Dat staat niet in de kennisbank; maak hiervoor een "
                      "ticket aan voor de Service Desk.",
            "sources": [],
            "hits": hits,
        }

    context = build_context(hits)
    user_prompt = f"Context uit de kennisbank:\n\n{context}\n\nVraag: {question}"
    reply = ask_llm(SYSTEM_PROMPT, user_prompt)

    unique_sources = sorted({hit["source"] for hit in hits})
    return {
        "answer": reply,
        "sources": unique_sources,
        "hits": hits,
    }


if __name__ == "__main__":
    # Snelle test vanaf de command line: python src/rag.py "mijn vraag"
    import sys
    q = " ".join(sys.argv[1:]) or "Hoe reset ik mijn wachtwoord?"
    out = answer(q)
    print("\nVraag:", q)
    print("\nAntwoord:\n", out["answer"])
    print("\nBronnen:", ", ".join(out["sources"]) or "(geen)")
