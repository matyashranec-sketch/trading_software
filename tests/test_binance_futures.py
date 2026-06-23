"""Tests for the Binance USD-M Futures broker (signing, sizing, long/short, close)."""
import httpx
import respx

from app.broker.base import LONG, SHORT
from app.broker.binance_futures import BinanceFuturesBroker

BASE = "https://testnet.binancefuture.com"

EXCHANGE_INFO = {
    "symbols": [{
        "symbol": "BTCUSDT",
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }],
}
ORDER_FILLED = {
    "orderId": 42, "symbol": "BTCUSDT", "status": "FILLED",
    "executedQty": "0.002", "cumQuote": "100", "avgPrice": "50000", "side": "BUY",
}


def _broker():
    return BinanceFuturesBroker(api_key="k", secret_key="s", testnet=True, leverage=3)


def _common_mocks():
    respx.get(f"{BASE}/fapi/v1/exchangeInfo").mock(return_value=httpx.Response(200, json=EXCHANGE_INFO))
    respx.get(f"{BASE}/fapi/v1/ticker/price").mock(
        return_value=httpx.Response(200, json={"symbol": "BTCUSDT", "price": "50000"}))
    respx.post(f"{BASE}/fapi/v1/leverage").mock(
        return_value=httpx.Response(200, json={"leverage": 3, "symbol": "BTCUSDT"}))


@respx.mock
def test_submit_buy_converts_notional_to_qty_and_signs():
    _common_mocks()
    order = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=ORDER_FILLED))
    res = _broker().submit_order("BTC", "buy", notional=100.0)

    req = order.calls.last.request
    url = str(req.url)
    assert "quantity=0.002" in url      # 100 / 50000, floored to 0.001 step
    assert "side=BUY" in url and "type=MARKET" in url
    assert "signature=" in url
    assert req.headers["X-MBX-APIKEY"] == "k"
    assert res.filled_avg_price == 50000.0 and res.status == "filled"


@respx.mock
def test_submit_sell_opens_short_side():
    _common_mocks()
    order = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=ORDER_FILLED))
    _broker().submit_order("BTC", "sell", notional=100.0)
    assert "side=SELL" in str(order.calls.last.request.url)
    assert "reduceOnly" not in str(order.calls.last.request.url)  # opening, not reducing


@respx.mock
def test_get_account_and_positions_long_and_short():
    respx.get(f"{BASE}/fapi/v2/account").mock(return_value=httpx.Response(200, json={
        "totalWalletBalance": "10000", "totalUnrealizedProfit": "50", "availableBalance": "9000",
    }))
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=[
        {"symbol": "BTCUSDT", "positionAmt": "0.5", "entryPrice": "48000",
         "markPrice": "50000", "unRealizedProfit": "1000"},
        {"symbol": "ETHUSDT", "positionAmt": "-2", "entryPrice": "3000",
         "markPrice": "2900", "unRealizedProfit": "200"},
        {"symbol": "SOLUSDT", "positionAmt": "0", "entryPrice": "0",
         "markPrice": "0", "unRealizedProfit": "0"},
    ]))
    broker = _broker()

    acct = broker.get_account()
    assert acct.equity == 10050.0 and acct.cash == 9000.0

    positions = broker.get_positions()
    assert len(positions) == 2  # zero-amount position skipped
    btc = next(p for p in positions if p.symbol == "BTC")
    eth = next(p for p in positions if p.symbol == "ETH")
    assert btc.side == LONG and btc.qty == 0.5 and btc.avg_entry_price == 48000
    assert eth.side == SHORT and eth.qty == 2 and eth.unrealized_pl == 200


@respx.mock
def test_close_short_buys_back_reduce_only():
    respx.get(f"{BASE}/fapi/v1/exchangeInfo").mock(return_value=httpx.Response(200, json=EXCHANGE_INFO))
    respx.get(f"{BASE}/fapi/v2/positionRisk").mock(return_value=httpx.Response(200, json=[
        {"symbol": "BTCUSDT", "positionAmt": "-0.3", "entryPrice": "50000",
         "markPrice": "49000", "unRealizedProfit": "300"},
    ]))
    order = respx.post(f"{BASE}/fapi/v1/order").mock(return_value=httpx.Response(200, json=ORDER_FILLED))

    _broker().close_position("BTC")
    url = str(order.calls.last.request.url)
    assert "side=BUY" in url           # closing a short -> buy back
    assert "reduceOnly=true" in url
    assert "quantity=0.3" in url
