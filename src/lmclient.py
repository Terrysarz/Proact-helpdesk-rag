"""
Dunne wrapper rond de LM Studio Python SDK (lmstudio-python).

Alle contact met LM Studio loopt via dit bestand. De SDK praat met de lokale
LM Studio server; er gaat niets naar buiten.

Docs: https://lmstudio.ai/docs/python
"""

from __future__ import annotations
import math
from typing import Iterator, Sequence

import lmstudio as lms

from config import LLM_MODEL, EMBEDDING_MODEL, MAX_TOKENS, SYSTEM_PROMPT

_llm = None
_embedder = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = lms.llm(LLM_MODEL)
    return _llm


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = lms.embedding_model(EMBEDDING_MODEL)
    return _embedder


def embed(text: str) -> list[float]:
    """Zet tekst om naar een embedding-vector (list van floats)."""
    result = get_embedder().embed(text)
    if hasattr(result, "embedding"):
        result = result.embedding
    if result and isinstance(result[0], (list, tuple)):
        result = result[0]
    return [float(x) for x in result]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_chat(user_prompt: str):
    chat = lms.Chat(SYSTEM_PROMPT)
    chat.add_user_message(user_prompt)
    return chat


def ask_llm(user_prompt: str) -> str:
    """Niet-streamend antwoord (gebruikt door de CLI)."""
    result = get_llm().respond(_build_chat(user_prompt), config={"maxTokens": MAX_TOKENS})
    return getattr(result, "content", str(result)).strip()


def ask_llm_stream(user_prompt: str) -> Iterator[str]:
    """
    Streamt het antwoord fragment voor fragment (gebruikt door de web-UI).
    Levert telkens een stukje tekst op zodra het model het genereert.
    """
    stream = get_llm().respond_stream(_build_chat(user_prompt), config={"maxTokens": MAX_TOKENS})
    for fragment in stream:
        text = getattr(fragment, "content", "")
        if text:
            yield text
