"""Broker interface + provider-agnostic dataclasses.

These dataclasses are what the rest of the app sees; concrete brokers (Alpaca)
adapt their SDK objects into these so nothing else depends on the SDK.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

LONG = "long"
SHORT = "short"


@dataclass
class Account:
    equity: float
    cash: float
    buying_power: float


@dataclass
class Position:
    symbol: str          # broker symbol as returned (e.g. "AAPL", "BTCUSD")
    qty: float           # signed-agnostic absolute quantity
    side: str            # long | short
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


@dataclass
class OrderResult:
    id: str
    symbol: str
    side: str            # buy | sell
    status: str          # accepted | filled | ...
    qty: float | None = None
    notional: float | None = None
    filled_avg_price: float | None = None


class Broker(ABC):
    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None: ...

    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        side: str,
        *,
        notional: float | None = None,
        qty: float | None = None,
    ) -> OrderResult: ...

    @abstractmethod
    def close_position(self, symbol: str) -> OrderResult: ...

    @abstractmethod
    def is_market_open(self) -> bool: ...

    @abstractmethod
    def list_open_orders(self) -> list[OrderResult]: ...
