"""Market microstructure data for the order-flow strategy.

The strategy needs more than a single last price: it needs **candles with taker
volume** (to reconstruct order flow / CVD), the **order book** (a small live
tiebreaker), and on futures the **funding rate / open interest** (crowding).

Design choice (mirrors :mod:`app.sources.prices`): market data always comes from
Binance **mainnet public** endpoints — real liquidity and real flow — even when
orders execute on the *testnet*. Testnet tapes are thin and unrealistic, so we
never read flow from them.

Key fact that makes the whole strategy backtestable: Binance klines include the
**taker buy base volume** per candle (index 9), so per-candle *delta* and a
**cumulative volume delta (CVD)** can be derived from history alone — no
websocket collector required.

All functions raise :class:`MarketDataUnavailable` on failure; callers (live
engine / backtest) decide whether to skip the asset.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"
_TIMEOUT = 20.0

# Per-call kline caps (Binance limits): spot 1000, futures 1500. Use the smaller
# so the same pagination math is safe on both.
_MAX_KLINES = 1000

# Interval string -> milliseconds (for paginating historical ranges).
_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


class MarketDataUnavailable(RuntimeError):
    pass


def interval_ms(interval: str) -> int:
    try:
        return _INTERVAL_MS[interval]
    except KeyError as exc:  # pragma: no cover - guard against typos in config
        raise MarketDataUnavailable(f"unknown interval {interval!r}") from exc


@dataclass(frozen=True, slots=True)
class Candle:
    """One OHLCV bar plus taker-buy volume (the order-flow ingredient)."""

    open_time: int            # epoch ms (bar open)
    open: float
    high: float
    low: float
    close: float
    volume: float             # base asset volume
    close_time: int           # epoch ms (bar close)
    quote_volume: float
    trades: int
    taker_buy_base: float     # base volume bought by aggressive (taker) buyers

    @property
    def delta(self) -> float:
        """Net aggressive volume in this bar: taker-buys minus taker-sells.

        Taker sells = total volume - taker buys, so delta = 2*taker_buy - volume.
        Positive = buyers were the aggressors, negative = sellers.
        """
        return 2.0 * self.taker_buy_base - self.volume

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Top-of-book snapshot (live tiebreaker only — not stored, not backtested)."""

    bids: tuple[tuple[float, float], ...]  # (price, qty), best first
    asks: tuple[tuple[float, float], ...]

    def imbalance(self, depth: int = 20) -> float:
        """Bid/ask volume imbalance in [-1, 1] over the top ``depth`` levels.

        +1 = all resting size on the bid (buy pressure), -1 = all on the ask.
        Returns 0.0 when the book is empty.
        """
        bid_vol = sum(q for _, q in self.bids[:depth])
        ask_vol = sum(q for _, q in self.asks[:depth])
        total = bid_vol + ask_vol
        if total <= 0:
            return 0.0
        return (bid_vol - ask_vol) / total


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _get(base: str, path: str, params: dict | None = None):
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{base}{path}", params=params or {})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise MarketDataUnavailable(f"GET {path} failed: {exc}") from exc


def _base_for(futures: bool) -> str:
    return FUTURES_BASE if futures else SPOT_BASE


def _klines_path(futures: bool) -> str:
    return "/fapi/v1/klines" if futures else "/api/v3/klines"


def _parse_klines(raw) -> list[Candle]:
    candles: list[Candle] = []
    for k in raw:
        try:
            candles.append(
                Candle(
                    open_time=int(k[0]),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    close_time=int(k[6]),
                    quote_volume=float(k[7]),
                    trades=int(k[8]),
                    taker_buy_base=float(k[9]),
                )
            )
        except (IndexError, TypeError, ValueError) as exc:  # pragma: no cover
            raise MarketDataUnavailable(f"bad kline row {k}: {exc}") from exc
    return candles


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def fetch_klines(
    pair: str,
    interval: str,
    limit: int = 300,
    *,
    futures: bool = False,
    end_ms: int | None = None,
) -> list[Candle]:
    """Most recent ``limit`` candles for ``pair`` on ``interval`` (oldest first).

    ``end_ms`` caps the window (used by the backtest to avoid lookahead).
    """
    params: dict = {"symbol": pair, "interval": interval, "limit": min(limit, _MAX_KLINES)}
    if end_ms is not None:
        params["endTime"] = end_ms
    candles = _parse_klines(_get(_base_for(futures), _klines_path(futures), params))
    if not candles:
        raise MarketDataUnavailable(f"no klines for {pair} {interval}")
    return candles


def fetch_klines_range(
    pair: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    *,
    futures: bool = False,
) -> list[Candle]:
    """Every candle in ``[start_ms, end_ms]`` (paginated). For backtests."""
    step = interval_ms(interval)
    out: list[Candle] = []
    cursor = start_ms
    base, path = _base_for(futures), _klines_path(futures)
    while cursor < end_ms:
        params = {
            "symbol": pair,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": _MAX_KLINES,
        }
        batch = _parse_klines(_get(base, path, params))
        if not batch:
            break
        out.extend(batch)
        last_open = batch[-1].open_time
        nxt = last_open + step
        if nxt <= cursor:  # no forward progress -> stop (guards against loops)
            break
        cursor = nxt
        if len(batch) < _MAX_KLINES:  # last page
            break
    # De-dup on open_time (paginated ranges can overlap by one bar).
    seen: set[int] = set()
    deduped: list[Candle] = []
    for c in out:
        if c.open_time in seen or c.open_time > end_ms:
            continue
        seen.add(c.open_time)
        deduped.append(c)
    return deduped


def fetch_depth(pair: str, limit: int = 100, *, futures: bool = False) -> OrderBook:
    """Order-book snapshot. Live-only tiebreaker (seconds-scale signal)."""
    path = "/fapi/v1/depth" if futures else "/api/v3/depth"
    data = _get(_base_for(futures), path, {"symbol": pair, "limit": limit})
    bids = tuple((float(p), float(q)) for p, q in data.get("bids", []))
    asks = tuple((float(p), float(q)) for p, q in data.get("asks", []))
    return OrderBook(bids=bids, asks=asks)


def fetch_funding_rate(pair: str) -> float:
    """Latest funding rate for a perpetual (futures only). >0 = longs pay shorts."""
    data = _get(FUTURES_BASE, "/fapi/v1/premiumIndex", {"symbol": pair})
    try:
        return float(data["lastFundingRate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataUnavailable(f"no funding for {pair}: {data}") from exc


def fetch_open_interest(pair: str) -> float:
    """Current open interest in base contracts (futures only)."""
    data = _get(FUTURES_BASE, "/fapi/v1/openInterest", {"symbol": pair})
    try:
        return float(data["openInterest"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataUnavailable(f"no open interest for {pair}: {data}") from exc
