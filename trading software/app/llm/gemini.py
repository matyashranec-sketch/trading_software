"""Google Gemini provider (free tier).

Uses the ``google-genai`` SDK. The API key is a free AI Studio key (no credit
card). ``available_models`` filters the configured list down to models the key
can actually use.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from app.config import Asset, get_settings
from app.llm.base import LLMProvider, PredictionResult
from app.llm.prompt import SYSTEM_INSTRUCTION, build_prompt, parse_result
from app.sources.news import NewsItem

logger = logging.getLogger(__name__)


class _GeminiSchema(BaseModel):
    """Structured-output schema handed to Gemini."""

    bullish_prob: float
    bearish_prob: float
    rationale: str


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, models: list[str] | None = None):
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()
        self._configured_models = models or list(settings.gemini_models)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def available_models(self) -> list[str]:
        if not self.api_key:
            return []
        try:
            client = self._get_client()
            supported = set()
            for m in client.models.list():
                name = (getattr(m, "name", "") or "").split("/")[-1]
                if name:
                    supported.add(name)
            usable = [m for m in self._configured_models if m in supported]
            if not usable:
                logger.warning(
                    "None of the configured Gemini models %s found among %d available; "
                    "using configured list as-is.",
                    self._configured_models,
                    len(supported),
                )
                return list(self._configured_models)
            return usable
        except Exception as exc:  # network / auth issues -> fall back, let predict() fail per-call
            logger.warning("Could not list Gemini models (%s); using configured list.", exc)
            return list(self._configured_models)

    def predict(self, model: str, asset: Asset, news: list[NewsItem]) -> PredictionResult:
        from google.genai import types

        client = self._get_client()
        prompt = build_prompt(asset, news)
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_GeminiSchema,
                temperature=0.7,
            ),
        )
        return _parse_response(resp)


def _parse_response(resp) -> PredictionResult:
    # Prefer the SDK-parsed object, fall back to raw JSON text.
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, _GeminiSchema):
        return parse_result(parsed.model_dump())
    if isinstance(parsed, dict):
        return parse_result(parsed)

    text = getattr(resp, "text", None)
    if not text:
        raise ValueError("Gemini returned an empty response")
    return parse_result(json.loads(text))
