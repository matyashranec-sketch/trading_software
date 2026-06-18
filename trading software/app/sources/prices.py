"""Current price fetching.

- Stocks -> Finnhub /quote  (field ``c`` = current price)
- Crypto -> CoinGecko /simple/price (no API key needed)

Raises ``PriceUnavailable`` when a price cannot be obtained; callers decide how
to handle it (predictor skips the asset, evaluator retries later).
"""
from __future__ import annotations

import httpx

from app.config import Asset, get_settings

FINNHUB_BASE = "https://finnhub.io/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_TIMEOUT = 20.0


class PriceUnavailable(RuntimeError):
    pass


def fetch_price(asset: Asset) -> float:
    if asset.kind == "crypto":
        return _fetch_coingecko_price(asset)
    return _fetch_finnhub_price(asset)


def _fetch_finnhub_price(asset: Asset) -> float:
    settings = get_settings()
    if not settings.has_finnhub:
        raise PriceUnavailable("FINNHUB_API_KEY not set")
    params = {"symbol": asset.symbol, "token": settings.finnhub_api_key}
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{FINNHUB_BASE}/quote", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise PriceUnavailable(f"Finnhub request failed for {asset.symbol}: {exc}") from exc

    price = data.get("c")
    if not price:  # 0 / None -> no data (e.g. unknown symbol or rate limited)
        raise PriceUnavailable(f"No price for {asset.symbol}: {data}")
    return float(price)


def _fetch_coingecko_price(asset: Asset) -> float:
    coin_id = asset.coingecko_id or asset.symbol.lower()
    params = {"ids": coin_id, "vs_currencies": "usd"}
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{COINGECKO_BASE}/simple/price", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise PriceUnavailable(f"CoinGecko request failed for {asset.symbol}: {exc}") from exc

    try:
        return float(data[coin_id]["usd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PriceUnavailable(f"No price for {asset.symbol}: {data}") from exc
