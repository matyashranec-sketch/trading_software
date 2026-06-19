import httpx
import pytest
import respx

from app.broker.binance import BinanceBroker, _base_of, _round_step, _to_pair

EXCHANGE_INFO = {
    "symbols": [
        {"symbol": "BTCUSDT", "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001000"},
            {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
        ]},
    ]
}


def _broker():
    return BinanceBroker(api_key="key", secret_key="secret", testnet=True)


# --- pure helpers ---
def test_round_step_floors_to_multiple():
    assert _round_step(0.123456, "0.00001000") == "0.12345"
    assert _round_step(1.0, "1.00000000") == "1"
    assert _round_step(0.5, None) == "0.5"


def test_symbol_mapping():
    assert _to_pair("BTC") == "BTCUSDT"
    assert _base_of("BTCUSDT") == "BTC"


# --- REST behaviour (mocked) ---
@respx.mock
def test_supports_via_exchange_info():
    respx.get("https://testnet.binance.vision/api/v3/exchangeInfo").mock(
        return_value=httpx.Response(200, json=EXCHANGE_INFO)
    )
    b = _broker()
    assert b.supports("BTC") is True
    assert b.supports("DOGE") is False


@respx.mock
def test_submit_buy_uses_quote_order_qty_and_signs():
    respx.get("https://testnet.binance.vision/api/v3/exchangeInfo").mock(
        return_value=httpx.Response(200, json=EXCHANGE_INFO)
    )
    order_route = respx.post("https://testnet.binance.vision/api/v3/order").mock(
        return_value=httpx.Response(200, json={
            "orderId": 123, "symbol": "BTCUSDT", "side": "BUY", "status": "FILLED",
            "executedQty": "0.00200000", "cummulativeQuoteQty": "100.00000000",
        })
    )
    result = _broker().submit_order("BTC", "buy", notional=100.0)

    assert result.id == "123"
    assert result.filled_avg_price == 50000.0  # 100 / 0.002
    req = order_route.calls.last.request
    assert req.url.params.get("quoteOrderQty") == "100.0"
    assert req.url.params.get("signature")
    assert req.headers.get("X-MBX-APIKEY") == "key"


@respx.mock
def test_submit_buy_below_min_notional_raises():
    respx.get("https://testnet.binance.vision/api/v3/exchangeInfo").mock(
        return_value=httpx.Response(200, json=EXCHANGE_INFO)
    )
    with pytest.raises(RuntimeError):
        _broker().submit_order("BTC", "buy", notional=1.0)  # below 5 USDT min


@respx.mock
def test_get_account_values_holdings():
    respx.get("https://testnet.binance.vision/api/v3/account").mock(
        return_value=httpx.Response(200, json={"balances": [
            {"asset": "USDT", "free": "1000.0", "locked": "0"},
            {"asset": "BTC", "free": "0.01", "locked": "0"},
        ]})
    )
    respx.get("https://api.binance.com/api/v3/ticker/price").mock(
        return_value=httpx.Response(200, json={"symbol": "BTCUSDT", "price": "50000.0"})
    )
    acct = _broker().get_account()
    assert acct.cash == 1000.0
    assert acct.equity == 1500.0  # 1000 + 0.01 * 50000
