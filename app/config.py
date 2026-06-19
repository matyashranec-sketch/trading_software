"""Central configuration: tracked assets, models, trading risk, settings.

Everything tunable lives here.  Secrets (API keys) are read from environment
variables / a local ``.env`` file (never committed) via pydantic-settings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    kind: str  # "stock" | "crypto"
    coingecko_id: str | None = None
    tradable: bool = True


# --- Tracked / tradable assets ---
ASSETS: list[Asset] = [
    Asset("TSLA", "Tesla", "stock"),
    Asset("AAPL", "Apple", "stock"),
    Asset("NVDA", "NVIDIA", "stock"),
    Asset("MSFT", "Microsoft", "stock"),
    Asset("BTC", "Bitcoin", "crypto", coingecko_id="bitcoin"),
]
ASSETS_BY_SYMBOL: dict[str, Asset] = {a.symbol: a for a in ASSETS}

# --- Accuracy-tracking horizons (each signal is scored against the real price) ---
HORIZONS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class Settings(BaseSettings):
    """Runtime settings, populated from environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets / data sources ---
    finnhub_api_key: str = ""          # news (+ stock price fallback)
    gemini_api_key: str = ""           # AI signal

    # --- Broker (Alpaca) ---
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    # Master safety switch. Default = paper (virtual money). Flip to true ONLY
    # with live keys and intent — see README.
    live_trading: bool = False

    # --- AI signal ---
    # Gemini models compared on the accuracy leaderboard. The first available one
    # (or ``trading_model`` if set & available) is the model the bot actually trades on.
    gemini_models: list[str] = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    trading_model: str = ""            # "" -> use first available model

    # --- Storage ---
    # Local default = SQLite. In production set DATABASE_URL to the Supabase
    # Postgres connection string (postgresql://...).
    database_url: str = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"

    # --- News fetching ---
    news_limit: int = 15               # headlines fed to the model per asset
    news_lookback_days: int = 3

    # --- Trading strategy / risk (the bot evaluates every ~2h via cron) ---
    min_confidence: float = 75.0       # only trade when max(bull,bear) >= this
    require_fresh_news: bool = True     # only trade when news is recent ("po news")
    news_fresh_hours: int = 24          # how recent "fresh" means
    max_position_pct: float = 0.10      # target position size per asset (of equity)
    max_open_positions: int = 5         # cap concurrent open positions
    cash_buffer_pct: float = 0.10       # never deploy this fraction of cash
    allow_short: bool = False           # bearish closes longs; shorts only if true
    scale_size_by_confidence: bool = False  # size *= confidence/100 when true
    stop_loss_pct: float = 0.0          # 0 = disabled; e.g. 0.08 = -8% hard stop
    take_profit_pct: float = 0.0        # 0 = disabled; e.g. 0.15 = +15% target

    # --- Optional local scheduler (production uses GitHub Actions cron) ---
    run_interval_hours: int = 2

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key.strip())

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_alpaca(self) -> bool:
        return bool(self.alpaca_api_key.strip() and self.alpaca_secret_key.strip())

    @property
    def alpaca_paper(self) -> bool:
        """Paper trading unless live_trading is explicitly enabled."""
        return not self.live_trading


@lru_cache
def get_settings() -> Settings:
    return Settings()
