"""Central configuration: tracked assets, prediction horizons, models, settings.

Everything tunable lives here.  Secrets (API keys) are read from a local ``.env``
file (never committed) via pydantic-settings.
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


# --- Tracked assets (monitor only) ---
ASSETS: list[Asset] = [
    Asset("TSLA", "Tesla", "stock"),
    Asset("AAPL", "Apple", "stock"),
    Asset("NVDA", "NVIDIA", "stock"),
    Asset("MSFT", "Microsoft", "stock"),
    Asset("BTC", "Bitcoin", "crypto", coingecko_id="bitcoin"),
]
ASSETS_BY_SYMBOL: dict[str, Asset] = {a.symbol: a for a in ASSETS}

# --- Prediction horizons (evaluated for every prediction) ---
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

    # Secrets
    finnhub_api_key: str = ""
    gemini_api_key: str = ""

    # Gemini model variants compared on the leaderboard. Availability with the
    # provided key is verified at runtime; unavailable ones are skipped.
    gemini_models: list[str] = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    # Storage
    database_url: str = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"

    # Scheduling (scheduler runs in UTC)
    prediction_hour: int = 13          # daily prediction run (UTC hour, 0-23)
    evaluation_interval_minutes: int = 60

    # News fetching
    news_limit: int = 15               # headlines fed to the model per asset
    news_lookback_days: int = 3

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key.strip())

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
