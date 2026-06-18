"""Pluggable LLM provider interface.

The rest of the app talks to AI only through ``LLMProvider`` so we can swap
Gemini for Ollama/Groq/etc. without touching the engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Asset
from app.sources.news import NewsItem


@dataclass
class PredictionResult:
    bullish_prob: float  # 0-100
    bearish_prob: float  # 0-100
    rationale: str


class LLMProvider(ABC):
    @abstractmethod
    def available_models(self) -> list[str]:
        """Configured models that actually work with the current credentials."""

    @abstractmethod
    def predict(
        self, model: str, asset: Asset, news: list[NewsItem]
    ) -> PredictionResult:
        """Ask one model to judge bullish/bearish from the news."""
