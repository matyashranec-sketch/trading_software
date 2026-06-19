"""Alpaca broker (paper by default).

Wraps the ``alpaca-py`` ``TradingClient`` and adapts its SDK objects into the
plain dataclasses from :mod:`app.broker.base`. The SDK is imported lazily so the
package can be imported (and the trader unit-tested with a fake broker) without
``alpaca-py`` installed or credentials configured.

Symbol mapping: stocks use the bare symbol ("AAPL"); crypto uses Alpaca's pair
notation ("BTC" -> "BTC/USD"). Positions may come back as "BTCUSD", so matching
is done loosely.
"""
from __future__ import annotations

from app.broker.base import LONG, SHORT, Account, Broker, OrderResult, Position
from app.config import ASSETS_BY_SYMBOL, get_settings


def _to_alpaca_symbol(symbol: str) -> str:
    asset = ASSETS_BY_SYMBOL.get(symbol)
    if asset is not None and asset.kind == "crypto":
        return f"{symbol}/USD"
    return symbol


def _is_crypto(symbol: str) -> bool:
    asset = ASSETS_BY_SYMBOL.get(symbol)
    return asset is not None and asset.kind == "crypto"


def _matches(position_symbol: str, config_symbol: str) -> bool:
    """True if an Alpaca position symbol corresponds to our config symbol."""
    p = position_symbol.upper().replace("/", "")
    c = config_symbol.upper()
    return p == c or p == f"{c}USD"


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AlpacaBroker(Broker):
    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 paper: bool | None = None):
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.alpaca_api_key
        self._secret_key = secret_key if secret_key is not None else settings.alpaca_secret_key
        self._paper = paper if paper is not None else settings.alpaca_paper
        self._client = None

    def _get_client(self):
        if self._client is None:
            from alpaca.trading.client import TradingClient

            self._client = TradingClient(
                api_key=self._api_key,
                secret_key=self._secret_key,
                paper=self._paper,
            )
        return self._client

    # --- Account / positions ---
    def get_account(self) -> Account:
        a = self._get_client().get_account()
        return Account(
            equity=float(a.equity),
            cash=float(a.cash),
            buying_power=float(a.buying_power),
        )

    def get_positions(self) -> list[Position]:
        return [self._adapt_position(p) for p in self._get_client().get_all_positions()]

    def get_position(self, symbol: str) -> Position | None:
        for p in self.get_positions():
            if _matches(p.symbol, symbol):
                return p
        return None

    @staticmethod
    def _adapt_position(p) -> Position:
        side = getattr(p.side, "value", str(p.side)).lower()
        return Position(
            symbol=p.symbol,
            qty=abs(_f(p.qty) or 0.0),
            side=SHORT if side == "short" else LONG,
            avg_entry_price=_f(p.avg_entry_price) or 0.0,
            market_value=_f(p.market_value) or 0.0,
            unrealized_pl=_f(p.unrealized_pl) or 0.0,
        )

    # --- Orders ---
    def submit_order(
        self,
        symbol: str,
        side: str,
        *,
        notional: float | None = None,
        qty: float | None = None,
    ) -> OrderResult:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        # Crypto trades 24/7 and needs GTC; fractional stock notional needs DAY.
        tif = TimeInForce.GTC if _is_crypto(symbol) else TimeInForce.DAY
        req = MarketOrderRequest(
            symbol=_to_alpaca_symbol(symbol),
            side=order_side,
            time_in_force=tif,
            notional=notional,
            qty=qty,
        )
        return self._adapt_order(self._get_client().submit_order(req))

    def close_position(self, symbol: str) -> OrderResult:
        return self._adapt_order(self._get_client().close_position(_to_alpaca_symbol(symbol)))

    def list_open_orders(self) -> list[OrderResult]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        orders = self._get_client().get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)
        )
        return [self._adapt_order(o) for o in orders]

    @staticmethod
    def _adapt_order(o) -> OrderResult:
        return OrderResult(
            id=str(o.id),
            symbol=o.symbol,
            side=getattr(o.side, "value", str(o.side)).lower(),
            status=getattr(o.status, "value", str(o.status)).lower(),
            qty=_f(o.qty),
            notional=_f(o.notional),
            filled_avg_price=_f(o.filled_avg_price),
        )

    # --- Market clock ---
    def is_market_open(self) -> bool:
        return bool(self._get_client().get_clock().is_open)
