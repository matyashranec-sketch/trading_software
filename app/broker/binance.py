"""Binance Spot Testnet broker (no KYC, free, fake funds).

Implements the :class:`~app.broker.base.Broker` interface against Binance's REST
API. Default endpoint is the Spot Testnet (``testnet.binance.vision``); set
``binance_testnet=False`` for real mainnet trading. Order execution + balances
use the configured (testnet) endpoint, while position valuation uses Binance
**mainnet** public prices for realism.

Symbol mapping: our config symbol ("BTC") -> Binance pair ("BTCUSDT").
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from decimal import ROUND_DOWN, Decimal

import httpx

from app.broker.base import LONG, Account, Broker, OrderResult, Position
from app.config import ASSETS_BY_SYMBOL, get_settings

logger = logging.getLogger(__name__)

TESTNET_BASE = "https://testnet.binance.vision"
MAINNET_BASE = "https://api.binance.com"
QUOTE = "USDT"
_TIMEOUT = 20.0
_RECV_WINDOW = 10_000
_DUST_USD = 1.0  # ignore balances worth less than this


def _to_pair(symbol: str) -> str:
    asset = ASSETS_BY_SYMBOL.get(symbol)
    if asset and asset.binance_symbol:
        return asset.binance_symbol
    return f"{symbol}{QUOTE}"


def _base_of(pair: str) -> str:
    return pair[: -len(QUOTE)] if pair.endswith(QUOTE) else pair


def _round_step(qty: float, step: str | None) -> str:
    """Floor a quantity to a multiple of the symbol's LOT_SIZE step."""
    if not step:
        return format(Decimal(str(qty)).normalize(), "f")
    stepd = Decimal(str(step))
    floored = (Decimal(str(qty)) // stepd) * stepd
    return format(floored.normalize(), "f")


class BinanceBroker(Broker):
    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 testnet: bool | None = None):
        s = get_settings()
        self._api_key = api_key if api_key is not None else s.binance_api_key
        secret = secret_key if secret_key is not None else s.binance_secret_key
        self._secret = secret.encode()
        self._testnet = testnet if testnet is not None else s.binance_testnet
        self._base = TESTNET_BASE if self._testnet else MAINNET_BASE
        self._filters: dict[str, dict] | None = None

    # --- low-level HTTP ---
    def _sign(self, params: dict) -> dict:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": _RECV_WINDOW}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        params["signature"] = hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()
        return params

    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False, base: str | None = None):
        base = base or self._base
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self._api_key} if signed else None
        if signed:
            params = self._sign(params)
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.request(method, f"{base}{path}", params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # --- prices (mainnet public) ---
    def _ticker_price(self, pair: str) -> float:
        data = self._request("GET", "/api/v3/ticker/price", {"symbol": pair}, base=MAINNET_BASE)
        return float(data["price"])

    # --- exchange filters / symbol validation ---
    def _load_filters(self) -> None:
        self._filters = {}
        data = self._request("GET", "/api/v3/exchangeInfo")
        for sym in data.get("symbols", []):
            entry = {"step": None, "min_notional": 0.0}
            for filt in sym.get("filters", []):
                if filt.get("filterType") == "LOT_SIZE":
                    entry["step"] = filt.get("stepSize")
                elif filt.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                    entry["min_notional"] = float(filt.get("minNotional", 0) or 0)
            self._filters[sym["symbol"]] = entry

    def _symbol_filters(self, pair: str) -> dict | None:
        if self._filters is None:
            self._load_filters()
        assert self._filters is not None
        return self._filters.get(pair)

    def supports(self, symbol: str) -> bool:
        """Whether this Binance endpoint lists the symbol's trading pair."""
        return self._symbol_filters(_to_pair(symbol)) is not None

    # --- Broker interface ---
    def get_account(self) -> Account:
        balances = self._balances()
        cash = balances.get(QUOTE, 0.0)
        equity = cash
        for asset, qty in balances.items():
            if asset == QUOTE or qty <= 0:
                continue
            try:
                equity += qty * self._ticker_price(f"{asset}{QUOTE}")
            except Exception:
                continue
        return Account(equity=equity, cash=cash, buying_power=cash)

    def get_positions(self) -> list[Position]:
        positions: list[Position] = []
        for asset, qty in self._balances().items():
            if asset == QUOTE or qty <= 0:
                continue
            try:
                price = self._ticker_price(f"{asset}{QUOTE}")
            except Exception:
                continue
            value = qty * price
            if value < _DUST_USD:
                continue
            positions.append(Position(symbol=asset, qty=qty, side=LONG, avg_entry_price=0.0,
                                      market_value=value, unrealized_pl=0.0))
        return positions

    def get_position(self, symbol: str) -> Position | None:
        base = symbol.upper()
        return next((p for p in self.get_positions() if p.symbol.upper() == base), None)

    def submit_order(self, symbol: str, side: str, *, notional: float | None = None,
                     qty: float | None = None) -> OrderResult:
        pair = _to_pair(symbol)
        filters = self._symbol_filters(pair)
        if filters is None:
            raise RuntimeError(f"{pair} is not tradable on this Binance endpoint")
        params = {"symbol": pair, "side": side.upper(), "type": "MARKET"}
        if side == "buy":
            if notional is None:
                raise ValueError("buy order requires notional")
            if notional < filters["min_notional"]:
                raise RuntimeError(f"{pair}: notional {notional} below min {filters['min_notional']}")
            params["quoteOrderQty"] = round(notional, 2)
        else:
            if qty is None:
                raise ValueError("sell order requires qty")
            params["quantity"] = _round_step(qty, filters["step"])
        return self._adapt_order(self._request("POST", "/api/v3/order", params, signed=True))

    def close_position(self, symbol: str) -> OrderResult:
        pair = _to_pair(symbol)
        pos = self.get_position(symbol)
        if pos is None or pos.qty <= 0:
            raise RuntimeError(f"no position to close for {symbol}")
        filters = self._symbol_filters(pair) or {"step": None}
        params = {"symbol": pair, "side": "SELL", "type": "MARKET",
                  "quantity": _round_step(pos.qty, filters["step"])}
        return self._adapt_order(self._request("POST", "/api/v3/order", params, signed=True))

    def is_market_open(self) -> bool:
        return True  # crypto trades 24/7

    def list_open_orders(self) -> list[OrderResult]:
        data = self._request("GET", "/api/v3/openOrders", signed=True)
        return [self._adapt_order(o) for o in data]

    # --- helpers ---
    def _balances(self) -> dict[str, float]:
        data = self._request("GET", "/api/v3/account", signed=True)
        return {b["asset"]: float(b["free"]) for b in data.get("balances", [])}

    @staticmethod
    def _adapt_order(o: dict) -> OrderResult:
        executed = float(o.get("executedQty", 0) or 0)
        quote = float(o.get("cummulativeQuoteQty", 0) or 0)
        avg = (quote / executed) if executed > 0 else None
        return OrderResult(
            id=str(o.get("orderId", "")),
            symbol=_base_of(o.get("symbol", "")),
            side=str(o.get("side", "")).lower(),
            status=str(o.get("status", "")).lower(),
            qty=executed or None,
            notional=quote or None,
            filled_avg_price=avg,
        )
