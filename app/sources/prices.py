"""Current price fetching.

Primary source is Alpaca market data (same provider that executes the trades),
when Alpaca credentials are configured. Fallbacks keep the app working without
them:

- Stocks -> Finnhub /quote  (field ``c`` = current price)
- Crypto -> CoinGecko /simple/price (no API key needed)

Raises ``PriceUnavailable`` when a price cannot be obtained; callers decide how
to handle it (signal generation skips the asset, evaluator retries later).
"""
from __future__ import annotations

import logging

import httpx

from app.config import Asset, Settings, get_settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_TIMEOUT = 20.0


class PriceUnavailable(RuntimeError):
    pass


BINANCE_BASE = "https://api.binance.com"


def fetch_price(asset: Asset) -> float:
    settings = get_settings()
    if asset.kind == "crypto":
        # Binance mainnet public price (realistic, no key) -> CoinGecko fallback.
        try:
            return _fetch_binance_price(asset)
        except Exception as exc:
            logger.warning("Binance price failed for %s (%s); falling back.", asset.symbol, exc)
        return _fetch_coingecko_price(asset)

    # Stocks (kept for the optional Alpaca broker path).
    if settings.has_alpaca:
        try:
            return _fetch_alpaca_price(asset, settings)
        except Exception as exc:
            logger.warning("Alpaca price failed for %s (%s); falling back.", asset.symbol, exc)
    return _fetch_finnhub_price(asset)


def _fetch_binance_price(asset: Asset) -> float:
    pair = asset.binance_symbol or f"{asset.symbol}USDT"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{BINANCE_BASE}/api/v3/ticker/price", params={"symbol": pair})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise PriceUnavailable(f"Binance request failed for {asset.symbol}: {exc}") from exc

    price = data.get("price")
    if not price:
        raise PriceUnavailable(f"No Binance price for {asset.symbol}: {data}")
    return float(price)


def _fetch_alpaca_price(asset: Asset, settings: Settings) -> float:
    if asset.kind == "crypto":
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoLatestTradeRequest

        pair = f"{asset.symbol}/USD"
        client = CryptoHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
        trade = client.get_crypto_latest_trade(CryptoLatestTradeRequest(symbol_or_symbols=pair))
        price = trade[pair].price
    else:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest

        client = StockHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
        trade = client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=asset.symbol)
        )
        price = trade[asset.symbol].price

    if not price:
        raise PriceUnavailable(f"Alpaca returned no price for {asset.symbol}")
    return float(price)


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
