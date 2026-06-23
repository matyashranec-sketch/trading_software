"""Broker abstraction.

The trading engine talks to a broker only through the ``Broker`` interface and
the plain dataclasses in :mod:`app.broker.base`, never to the Alpaca SDK
directly — so it can be swapped or faked in tests.
"""
from __future__ import annotations

from app.broker.base import Account, Broker, OrderResult, Position


def get_broker() -> Broker:
    """Return the configured broker (``BROKER`` setting; Binance futures by default)."""
    from app.config import get_settings

    broker = get_settings().broker
    if broker == "alpaca":
        from app.broker.alpaca import AlpacaBroker

        return AlpacaBroker()

    if broker == "binance":
        from app.broker.binance import BinanceBroker

        return BinanceBroker()

    from app.broker.binance_futures import BinanceFuturesBroker

    return BinanceFuturesBroker()


__all__ = ["Account", "Broker", "OrderResult", "Position", "get_broker"]
