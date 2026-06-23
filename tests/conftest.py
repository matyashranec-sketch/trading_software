import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  register mappers
from app.broker.base import LONG, SHORT, Account, Broker, OrderResult, Position
from app.db import Base


@pytest.fixture
def db():
    """Isolated in-memory SQLite session per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class FakeBroker(Broker):
    """In-memory broker that records orders instead of hitting Alpaca."""

    def __init__(self, *, equity=10_000.0, cash=10_000.0, buying_power=10_000.0,
                 positions=None, market_open=True, open_orders=None, fill_price=None):
        self.account = Account(equity=equity, cash=cash, buying_power=buying_power)
        self.positions = list(positions or [])
        self.market_open = market_open
        self.open_orders = list(open_orders or [])
        self.fill_price = fill_price
        self.submitted: list[tuple] = []   # (symbol, side, notional, qty)
        self.closed: list[str] = []
        self._next_id = 1

    def _new_id(self) -> str:
        oid = str(self._next_id)
        self._next_id += 1
        return oid

    def get_account(self):
        return self.account

    def get_positions(self):
        return list(self.positions)

    def get_position(self, symbol):
        for p in self.positions:
            if p.symbol.upper().replace("/", "").startswith(symbol.upper()):
                return p
        return None

    def submit_order(self, symbol, side, *, notional=None, qty=None):
        self.submitted.append((symbol, side, notional, qty))
        return OrderResult(id=self._new_id(), symbol=symbol, side=side, status="accepted",
                           notional=notional, qty=qty, filled_avg_price=self.fill_price)

    def close_position(self, symbol):
        self.closed.append(symbol)
        return OrderResult(id=self._new_id(), symbol=symbol, side="sell", status="accepted")

    def is_market_open(self):
        return self.market_open

    def list_open_orders(self):
        return list(self.open_orders)


def long_position(symbol, qty, avg_entry_price, market_value=None):
    mv = market_value if market_value is not None else qty * avg_entry_price
    return Position(symbol=symbol, qty=qty, side=LONG, avg_entry_price=avg_entry_price,
                    market_value=mv, unrealized_pl=0.0)


def short_position(symbol, qty, avg_entry_price, market_value=None):
    mv = market_value if market_value is not None else qty * avg_entry_price
    return Position(symbol=symbol, qty=qty, side=SHORT, avg_entry_price=avg_entry_price,
                    market_value=mv, unrealized_pl=0.0)
