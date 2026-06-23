"""Tests for the order-flow market-data layer (Binance klines/depth/funding)."""
import httpx
import respx

from app.sources.market_data import (
    OrderBook,
    fetch_funding_rate,
    fetch_klines,
    fetch_klines_range,
    fetch_open_interest,
)


def _kline(open_time, o, h, low, c, vol, taker_buy, *, step=3_600_000):
    """Build a raw Binance kline row (12 fields)."""
    return [
        open_time, f"{o}", f"{h}", f"{low}", f"{c}", f"{vol}",
        open_time + step - 1, "0", 100, f"{taker_buy}", "0", "0",
    ]


@respx.mock
def test_fetch_klines_parses_fields_and_delta():
    rows = [
        _kline(0, 100, 110, 95, 105, 1000, 700),   # buyers aggressive
        _kline(3_600_000, 105, 106, 90, 92, 800, 200),  # sellers aggressive
    ]
    respx.get("https://api.binance.com/api/v3/klines").mock(
        return_value=httpx.Response(200, json=rows)
    )
    candles = fetch_klines("BTCUSDT", "1h", limit=2)
    assert len(candles) == 2
    c0 = candles[0]
    assert (c0.open, c0.high, c0.low, c0.close, c0.volume) == (100, 110, 95, 105, 1000)
    assert c0.taker_buy_base == 700
    # delta = 2*taker_buy - volume
    assert c0.delta == 2 * 700 - 1000          # +400 (net buying)
    assert candles[1].delta == 2 * 200 - 800   # -400 (net selling)
    assert c0.is_bullish and not candles[1].is_bullish


@respx.mock
def test_fetch_klines_range_dedups_and_clips_end():
    end = 10_000_000
    rows = [
        _kline(0, 1, 2, 0.5, 1.5, 10, 6),
        _kline(3_600_000, 1.5, 2, 1, 1.8, 10, 7),
        _kline(3_600_000, 1.5, 2, 1, 1.8, 10, 7),     # duplicate open_time
        _kline(end + 3_600_000, 9, 9, 9, 9, 1, 1),    # beyond end_ms -> dropped
    ]
    respx.get("https://api.binance.com/api/v3/klines").mock(
        return_value=httpx.Response(200, json=rows)
    )
    candles = fetch_klines_range("BTCUSDT", "1h", 0, end)
    open_times = [c.open_time for c in candles]
    assert open_times == [0, 3_600_000]  # deduped + clipped


def test_orderbook_imbalance():
    book = OrderBook(bids=((100.0, 8.0), (99.0, 2.0)), asks=((101.0, 1.0), (102.0, 1.0)))
    # bids 10 vs asks 2 -> (10-2)/12
    assert round(book.imbalance(), 4) == round(8 / 12, 4)
    assert OrderBook(bids=(), asks=()).imbalance() == 0.0


@respx.mock
def test_futures_klines_hit_fapi_host():
    respx.get("https://fapi.binance.com/fapi/v1/klines").mock(
        return_value=httpx.Response(200, json=[_kline(0, 1, 1, 1, 1, 1, 1)])
    )
    candles = fetch_klines("BTCUSDT", "1h", limit=1, futures=True)
    assert len(candles) == 1


@respx.mock
def test_fetch_funding_and_open_interest():
    respx.get("https://fapi.binance.com/fapi/v1/premiumIndex").mock(
        return_value=httpx.Response(200, json={"lastFundingRate": "0.00012"})
    )
    respx.get("https://fapi.binance.com/fapi/v1/openInterest").mock(
        return_value=httpx.Response(200, json={"openInterest": "12345.6"})
    )
    assert abs(fetch_funding_rate("BTCUSDT") - 0.00012) < 1e-9
    assert fetch_open_interest("BTCUSDT") == 12345.6
