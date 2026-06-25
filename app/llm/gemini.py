"""Google Gemini provider (free tier).

Uses the ``google-genai`` SDK. The API key is a free AI Studio key (no credit
card). ``available_models`` filters the configured list down to models the key
can actually use.

The free tier rate-limits per minute (429 ``TooManyRequests``) and the model is
sometimes overloaded (503 ``ServiceUnavailable``). To stay reliable on a single
key we (1) **retry** transient errors with exponential backoff + jitter,
(2) **throttle** calls so a burst of per-asset requests stays under the limit,
and (3) **cache** the model list so we don't re-list every cycle.
"""
from __future__ import annotations

import json
import logging
import random
import time

from pydantic import BaseModel

from app.config import Asset, get_settings
from app.llm.base import LLMProvider, PredictionResult
from app.llm.prompt import (
    SETUP_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    build_prompt,
    build_setup_prompt,
    parse_result,
)
from app.sources.news import NewsItem

logger = logging.getLogger(__name__)

# HTTP statuses worth retrying: rate limit + transient server/overload errors.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# google-genai also surfaces a string status; treat these the same way.
_RETRYABLE_STATUS_STR = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"}

# Process-wide cache of the usable model list, keyed by API key: {key: (monotonic_ts, models)}.
# The bot runs as a long-lived process, so this turns a per-cycle models.list()
# call into roughly one call per `gemini_models_cache_ttl`.
_models_cache: dict[str, tuple[float, list[str]]] = {}


def _status_of(exc: Exception) -> int | None:
    """Best-effort HTTP status from a google-genai error (duck-typed for tests)."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    try:
        return int(code)  # e.g. code given as a numeric string
    except (TypeError, ValueError):
        return None


def _is_retryable(exc: Exception) -> bool:
    if _status_of(exc) in _RETRYABLE_STATUS:
        return True
    status = getattr(exc, "status", None)
    return isinstance(status, str) and status.upper() in _RETRYABLE_STATUS_STR


def _retry_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff (base*2**attempt) capped at ``cap``, plus jitter."""
    return min(cap, base * (2 ** attempt)) + random.uniform(0, base)


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
        self._last_call = 0.0  # monotonic timestamp of the last model call (throttle)

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def available_models(self) -> list[str]:
        if not self.api_key:
            return []
        ttl = get_settings().gemini_models_cache_ttl
        cached = _models_cache.get(self.api_key)
        if cached and (time.monotonic() - cached[0]) < ttl:
            return list(cached[1])
        try:
            models = self._fetch_available_models()
        except Exception as exc:  # network / auth issues -> fall back, let predict() fail per-call
            logger.warning("Could not list Gemini models (%s); using configured list.", exc)
            return list(self._configured_models)  # not cached -> retried next cycle
        _models_cache[self.api_key] = (time.monotonic(), models)
        return list(models)

    def _fetch_available_models(self) -> list[str]:
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

    def predict(self, model: str, asset: Asset, news: list[NewsItem]) -> PredictionResult:
        client = self._get_client()
        prompt = build_prompt(asset, news)
        config = self._build_config(SYSTEM_INSTRUCTION, temperature=0.7)
        resp = self._generate_with_retry(client, model, prompt, config)
        return _parse_response(resp)

    def judge_setup(self, model: str, asset: Asset, setup: dict) -> PredictionResult:
        """Confirm or reject a quantitative order-flow setup (the trader's 2nd gate).

        Same structured-output contract as :meth:`predict` (bullish/bearish probs +
        rationale), but the prompt is the order-flow breakdown, not news, and the
        temperature is lower for steadier verdicts.
        """
        client = self._get_client()
        prompt = build_setup_prompt(asset, setup)
        config = self._build_config(SETUP_SYSTEM_INSTRUCTION, temperature=0.3)
        resp = self._generate_with_retry(client, model, prompt, config)
        return _parse_response(resp)

    def _build_config(self, system_instruction: str = SYSTEM_INSTRUCTION, temperature: float = 0.7):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=_GeminiSchema,
            temperature=temperature,
        )

    def _generate_with_retry(self, client, model: str, prompt, config):
        """Call ``generate_content``, retrying transient 429/5xx with backoff."""
        settings = get_settings()
        max_retries = settings.gemini_max_retries
        for attempt in range(max_retries + 1):
            self._throttle()
            try:
                return client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
            except Exception as exc:
                if attempt < max_retries and _is_retryable(exc):
                    delay = _retry_delay(
                        attempt, settings.gemini_retry_base_delay, settings.gemini_retry_max_delay
                    )
                    logger.warning(
                        "Gemini %s transient error (status=%s); retrying in %.1fs (attempt %d/%d)",
                        model, _status_of(exc), delay, attempt + 1, max_retries,
                    )
                    time.sleep(delay)
                    continue
                raise

    def _throttle(self) -> None:
        """Sleep just enough to keep model calls ``llm_min_interval_seconds`` apart."""
        interval = get_settings().llm_min_interval_seconds
        if interval <= 0:
            return
        wait = interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


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
