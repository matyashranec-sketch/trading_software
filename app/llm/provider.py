"""Provider factory — single place to swap the AI backend.

To switch to local models later, return a different ``LLMProvider`` here
(e.g. an ``OllamaProvider``) and nothing else in the app needs to change.
"""
from __future__ import annotations

from app.llm.base import LLMProvider
from app.llm.gemini import GeminiProvider


def get_provider() -> LLMProvider:
    return GeminiProvider()
