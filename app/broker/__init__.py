"""Broker abstraction.

The trading engine talks to a broker only through the ``Broker`` interface and
the plain dataclasses in :mod:`app.broker.base`, never to the Alpaca SDK
directly — so it can be swapped or faked in tests.
"""
from __future__ import annotations

from app.broker.base import Account, Broker, OrderResult, Position


def get_broker() -> Broker:
    """Return the configured broker (Alpaca paper/live based on settings)."""
    from app.broker.alpaca import AlpacaBroker

    return AlpacaBroker()


__all__ = ["Account", "Broker", "OrderResult", "Position", "get_broker"]
