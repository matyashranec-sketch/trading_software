"""Retry / backoff behaviour of the Gemini provider.

We don't hit the real API: ``_get_client`` is replaced with a fake whose
``generate_content`` raises a configurable number of times (with a given HTTP
status) before returning a valid structured response. ``time.sleep`` is patched
out so the test is instant.
"""
from types import SimpleNamespace

import pytest

import app.llm.gemini as gemini_mod
from app.config import ASSETS
from app.llm.base import PredictionResult
from app.llm.gemini import GeminiProvider, _GeminiSchema


class _FakeAPIError(Exception):
    """Mimics google-genai errors: carries an HTTP ``code`` attribute."""

    def __init__(self, code: int):
        super().__init__(f"fake API error {code}")
        self.code = code


class _FakeModels:
    def __init__(self, errors_before_success: int, code: int):
        self._remaining = errors_before_success
        self._code = code
        self.calls = 0

    def generate_content(self, *, model, contents, config):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise _FakeAPIError(self._code)
        return SimpleNamespace(
            parsed=_GeminiSchema(bullish_prob=70, bearish_prob=30, rationale="ok")
        )


@pytest.fixture
def no_sleep(monkeypatch):
    """Make both the backoff and the throttle instant."""
    monkeypatch.setattr(gemini_mod.time, "sleep", lambda *_a, **_k: None)


def _provider_with(fake_models, monkeypatch):
    provider = GeminiProvider(api_key="test-key", models=["gemini-2.5-flash"])
    monkeypatch.setattr(provider, "_get_client", lambda: SimpleNamespace(models=fake_models))
    # Don't touch the real google-genai SDK just to build a request config.
    monkeypatch.setattr(provider, "_build_config", lambda: None)
    return provider


def test_predict_retries_transient_503_then_succeeds(no_sleep, monkeypatch):
    fake = _FakeModels(errors_before_success=2, code=503)
    provider = _provider_with(fake, monkeypatch)

    result = provider.predict("gemini-2.5-flash", ASSETS[0], [])

    assert isinstance(result, PredictionResult)
    assert result.bullish_prob == 70
    assert fake.calls == 3  # 2 failures + 1 success


def test_predict_does_not_retry_client_error_400(no_sleep, monkeypatch):
    fake = _FakeModels(errors_before_success=5, code=400)
    provider = _provider_with(fake, monkeypatch)

    with pytest.raises(_FakeAPIError):
        provider.predict("gemini-2.5-flash", ASSETS[0], [])

    assert fake.calls == 1  # non-retryable -> fails immediately


def test_predict_gives_up_after_max_retries(no_sleep, monkeypatch):
    # Always-503: should try once + gemini_max_retries times, then re-raise.
    from app.config import get_settings

    fake = _FakeModels(errors_before_success=999, code=503)
    provider = _provider_with(fake, monkeypatch)

    with pytest.raises(_FakeAPIError):
        provider.predict("gemini-2.5-flash", ASSETS[0], [])

    assert fake.calls == get_settings().gemini_max_retries + 1
