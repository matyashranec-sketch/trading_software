"""News fetching from Finnhub.

- Stocks  -> /company-news (symbol specific)
- Crypto  -> /news?category=crypto (general crypto feed)

Returns an empty list (never raises) when no API key is configured, so the app
keeps running without keys.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

import httpx

from app.config import Asset, Settings, get_settings
from app.models import utcnow

FINNHUB_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 20.0


@dataclass
class NewsItem:
    headline: str
    summary: str
    source: str
    url: str
    datetime: int  # unix seconds

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_news(asset: Asset, limit: int | None = None) -> list[NewsItem]:
    """Fetch the most recent headlines for an asset. Newest first."""
    settings = get_settings()
    if not settings.has_finnhub:
        return []

    limit = limit or settings.news_limit
    if asset.kind == "crypto":
        items = _fetch_crypto_news(settings)
        # Finnhub's crypto feed is one general stream — narrow it to this coin.
        # Fall back to the general feed if nothing matches (still useful context).
        items = _filter_by_terms(items, asset.news_terms) or items
    else:
        items = _fetch_company_news(asset.symbol, settings)

    items.sort(key=lambda n: n.datetime, reverse=True)
    return items[:limit]


def _filter_by_terms(items: list[NewsItem], terms: tuple[str, ...]) -> list[NewsItem]:
    if not terms:
        return items
    lowered = [t.lower() for t in terms]
    return [
        n for n in items
        if any(t in f"{n.headline} {n.summary}".lower() for t in lowered)
    ]


def _fetch_company_news(symbol: str, settings: Settings) -> list[NewsItem]:
    today = utcnow().date()
    frm = today - timedelta(days=settings.news_lookback_days)
    params = {
        "symbol": symbol,
        "from": frm.isoformat(),
        "to": today.isoformat(),
        "token": settings.finnhub_api_key,
    }
    return _get(f"{FINNHUB_BASE}/company-news", params)


def _fetch_crypto_news(settings: Settings) -> list[NewsItem]:
    params = {"category": "crypto", "token": settings.finnhub_api_key}
    return _get(f"{FINNHUB_BASE}/news", params)


def _get(url: str, params: dict) -> list[NewsItem]:
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list):
        return []
    return [_parse(item) for item in data if item.get("headline")]


def _parse(item: dict) -> NewsItem:
    return NewsItem(
        headline=(item.get("headline") or "").strip(),
        summary=(item.get("summary") or "").strip(),
        source=(item.get("source") or "").strip(),
        url=(item.get("url") or "").strip(),
        datetime=int(item.get("datetime") or 0),
    )
