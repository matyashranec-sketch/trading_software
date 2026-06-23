"""Binance USD-M Futures Testnet broker (order-flow strategy: long + short).

Implements the :class:`~app.broker.base.Broker` interface against Binance's
**futures** REST API (``fapi``). Default endpoint is the Futures Testnet
(``testnet.binancefuture.com``) — a *separate* signup from the spot testnet.

Why futures: the order-flow strategy is symmetric (it shorts as readily as it
longs) and CVD/flow signals are strongest on perpetuals. Futures also reports
real per-position entry price, unrealized PnL and liquidation price (spot does
not), so position fidelity is higher.

Assumes **one-way** position mode (the account default): ``positionAmt`` is
signed (>0 long, <0 short) and closing uses ``reduceOnly``.

Signing mirrors :mod:`app.broker.binance` (HMAC-SHA256 over the query +
timestamp, ``X-MBX-APIKEY`` header). Orders are sized by base ``quantity``
(notional is converted via the current price and floored to LOT_SIZE).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

import httpx

from app.broker.base import LONG, SHORT, Account, Broker, OrderResult, Position
from app.broker.binance import _base_of, _round_step, _to_pair
from app.config import get_settings

logger = logging.getLogger(__name__)

TESTNET_BASE = "https://testnet.binancefuture.com"
MAINNET_BASE = "https://fapi.binance.com"
_TIMEOUT = 20.0
_RECV_WINDOW = 10_000


class BinanceFuturesBroker(Broker):
    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 testnet: bool | None = None, leverage: int | None = None):
        s = get_settings()
        self._api_key = api_key if api_key is not None else s.binance_futures_api_key
        secret = secret_key if secret_key is not None else s.binance_futures_secret_key
        self._secret = secret.encode()
        self._testnet = testnet if testnet is not None else s.binance_futures_testnet
        self._base = TESTNET_BASE if self._testnet else MAINNET_BASE
        self._leverage = leverage if leverage is not None else s.futures_leverage
        self._filters: dict[str, dict] | None = None
        self._leveraged: set[str] = set()

    # --- low-level HTTP ---
    def _sign(self, params: dict) -> dict:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": _RECV_WINDOW}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        params["signature"] = hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()
        return params

    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False):
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self._api_key} if signed else None
        if signed:
            params = self._sign(params)
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.request(method, f"{self._base}{path}", params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def _ticker_price(self, pair: str) -> float:
        data = self._request("GET", "/fapi/v1/ticker/price", {"symbol": pair})
        return float(data["price"])

    # --- exchange filters ---
    def _load_filters(self) -> None:
        self._filters = {}
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        for sym in data.get("symbols", []):
            entry = {"step": None, "min_notional": 0.0}
            for filt in sym.get("filters", []):
                if filt.get("filterType") == "LOT_SIZE":
                    entry["step"] = filt.get("stepSize")
                elif filt.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                    entry["min_notional"] = float(filt.get("notional", filt.get("minNotional", 0)) or 0)
            self._filters[sym["symbol"]] = entry

    def _symbol_filters(self, pair: str) -> dict | None:
        if self._filters is None:
            self._load_filters()
        assert self._filters is not None
        return self._filters.get(pair)

    def supports(self, symbol: str) -> bool:
        return self._symbol_filters(_to_pair(symbol)) is not None

    def _ensure_leverage(self, pair: str) -> None:
        if pair in self._leveraged:
            return
        try:
            self._request("POST", "/fapi/v1/leverage",
                          {"symbol": pair, "leverage": self._leverage}, signed=True)
        except Exception as exc:  # not fatal — order can still go through at current leverage
            logger.warning("Could not set leverage for %s: %s", pair, exc)
        self._leveraged.add(pair)

    # --- Broker interface ---
    def get_account(self) -> Account:
        data = self._request("GET", "/fapi/v2/account", signed=True)
        wallet = float(data.get("totalWalletBalance", 0) or 0)
        unrealized = float(data.get("totalUnrealizedProfit", 0) or 0)
        available = float(data.get("availableBalance", 0) or 0)
        return Account(equity=wallet + unrealized, cash=available, buying_power=available)

    def get_positions(self) -> list[Position]:
        data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        positions: list[Position] = []
        for p in data:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            mark = float(p.get("markPrice", 0) or 0)
            positions.append(Position(
                symbol=_base_of(p.get("symbol", "")),
                qty=abs(amt),
                side=LONG if amt > 0 else SHORT,
                avg_entry_price=float(p.get("entryPrice", 0) or 0),
                market_value=abs(amt) * mark,
                unrealized_pl=float(p.get("unRealizedProfit", 0) or 0),
            ))
        return positions

    def get_position(self, symbol: str) -> Position | None:
        base = symbol.upper()
        return next((p for p in self.get_positions() if p.symbol.upper() == base), None)

    def submit_order(self, symbol: str, side: str, *, notional: float | None = None,
                     qty: float | None = None) -> OrderResult:
        pair = _to_pair(symbol)
        filters = self._symbol_filters(pair)
        if filters is None:
            raise RuntimeError(f"{pair} is not tradable on this Binance futures endpoint")
        self._ensure_leverage(pair)
        if qty is None:
            if notional is None:
                raise ValueError("order requires notional or qty")
            if notional < filters["min_notional"]:
                raise RuntimeError(f"{pair}: notional {notional} below min {filters['min_notional']}")
            qty = notional / self._ticker_price(pair)
        params = {
            "symbol": pair, "side": side.upper(), "type": "MARKET",
            "quantity": _round_step(qty, filters["step"]),
        }
        return self._adapt_order(self._request("POST", "/fapi/v1/order", params, signed=True))

    def close_position(self, symbol: str) -> OrderResult:
        pair = _to_pair(symbol)
        pos = self.get_position(symbol)
        if pos is None or pos.qty <= 0:
            raise RuntimeError(f"no position to close for {symbol}")
        filters = self._symbol_filters(pair) or {"step": None}
        side = "SELL" if pos.side == LONG else "BUY"  # reduce in the opposite direction
        params = {
            "symbol": pair, "side": side, "type": "MARKET", "reduceOnly": "true",
            "quantity": _round_step(pos.qty, filters["step"]),
        }
        return self._adapt_order(self._request("POST", "/fapi/v1/order", params, signed=True))

    def is_market_open(self) -> bool:
        return True  # crypto perps trade 24/7

    def list_open_orders(self) -> list[OrderResult]:
        data = self._request("GET", "/fapi/v1/openOrders", signed=True)
        return [self._adapt_order(o) for o in data]

    @staticmethod
    def _adapt_order(o: dict) -> OrderResult:
        executed = float(o.get("executedQty", 0) or 0)
        quote = float(o.get("cumQuote", 0) or 0)
        avg = float(o.get("avgPrice", 0) or 0) or (quote / executed if executed > 0 else None)
        return OrderResult(
            id=str(o.get("orderId", "")),
            symbol=_base_of(o.get("symbol", "")),
            side=str(o.get("side", "")).lower(),
            status=str(o.get("status", "")).lower(),
            qty=executed or None,
            notional=quote or None,
            filled_avg_price=avg,
        )
