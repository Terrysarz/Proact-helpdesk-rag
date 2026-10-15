"""
Dunne wrapper rond de LM Studio Python SDK (lmstudio-python).

Alle contact met LM Studio loopt via dit bestand, zodat ingest.py en rag.py
dezelfde modellen en embed-logica delen. De SDK praat met de lokale LM Studio
server (standaard op dezelfde machine); er gaat dus niets naar buiten.

Docs: https://lmstudio.ai/docs/python  en  /docs/python/embedding
"""

from __future__ import annotations
import math
from typing import Sequence

import lmstudio as lms

from config import LLM_MODEL, EMBEDDING_MODEL

# De modelhandles worden pas bij eerste gebruik geladen (lazy) en daarna
# hergebruikt, zodat het model niet per vraag opnieuw wordt ingeladen.
_llm = None
_embedder = None


def get_llm():
    """Geeft (en cachet) het LLM dat de antwoorden genereert."""
    global _llm
    if _llm is None:
        _llm = lms.llm(LLM_MODEL)
    return _llm


def get_embedder():
    """Geeft (en cachet) het embedding-model."""
    global _embedder
    if _embedder is None:
        _embedder = lms.embedding_model(EMBEDDING_MODEL)
    return _embedder


def embed(text: str) -> list[float]:
    """
    Zet één stuk tekst om naar een embedding-vector (list van floats).

    De SDK kan afhankelijk van de versie een list of een objectje teruggeven;
    we maken er defensief altijd een platte list[float] van.
    """
    result = get_embedder().embed(text)

    # Mogelijke vormen afvangen: list[float], object met .embedding, of
    # list met één embedding erin.
    if hasattr(result, "embedding"):
        result = result.embedding
    if result and isinstance(result[0], (list, tuple)):
        result = result[0]
    return [float(x) for x in result]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine-similarity tussen twee vectoren (0 = ongerelateerd, 1 = identiek)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def ask_llm(system_prompt: str, user_prompt: str) -> str:
    """Stelt het LLM een vraag met systeem- + gebruikersprompt en geeft tekst terug."""
    chat = lms.Chat(system_prompt)
    chat.add_user_message(user_prompt)
    result = get_llm().respond(chat)
    # PredictionResult heeft .content; str() werkt ook als fallback.
    return getattr(result, "content", str(result)).strip()
