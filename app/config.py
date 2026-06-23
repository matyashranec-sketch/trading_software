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
    binance_symbol: str | None = None        # trading pair on Binance, e.g. "BTCUSDT"
    news_terms: tuple[str, ...] = ()          # keywords to filter the crypto news feed


# --- Tracked assets (crypto-only, traded vs USDT on Binance) ---
# Only BTC + BNB are tradable right now: they're the coins with a backtested
# order-flow edge (reversal; the OOS optimizer flagged them as the profitable
# 2/5). ETH/SOL showed no edge in either reversal or momentum, and XRP was only
# noise-level positive (+0.44%/PF 1.06 full-period). The non-tradable coins stay
# in the list so the accuracy leaderboard keeps scoring them, but the trader and
# the default backtest/optimize basket skip them. Flip tradable=True again once a
# backtest (+ out-of-sample optimize) shows a real edge for that coin.
ASSETS: list[Asset] = [
    Asset("BTC", "Bitcoin", "crypto", coingecko_id="bitcoin",
          binance_symbol="BTCUSDT", news_terms=("bitcoin", "btc")),
    Asset("ETH", "Ethereum", "crypto", coingecko_id="ethereum", tradable=False,
          binance_symbol="ETHUSDT", news_terms=("ethereum", "eth", "ether")),
    Asset("SOL", "Solana", "crypto", coingecko_id="solana", tradable=False,
          binance_symbol="SOLUSDT", news_terms=("solana", "sol")),
    Asset("BNB", "BNB", "crypto", coingecko_id="binancecoin",
          binance_symbol="BNBUSDT", news_terms=("bnb", "binance coin", "binance")),
    Asset("XRP", "XRP", "crypto", coingecko_id="ripple", tradable=False,
          binance_symbol="XRPUSDT", news_terms=("xrp", "ripple")),
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

    # --- Broker selection ---
    # "binance_futures" -> Binance USD-M Futures Testnet (order-flow strategy; long+short).
    # "binance"         -> Binance Spot Testnet (no KYC, free, fake funds).
    # "alpaca"          -> Alpaca paper/live (kept as an optional alternative).
    broker: str = "binance_futures"

    # --- Broker: Binance Spot (Testnet by default) ---
    binance_api_key: str = ""
    binance_secret_key: str = ""
    # Default = testnet (fake funds, no KYC). Set false ONLY for real mainnet trading.
    binance_testnet: bool = True

    # --- Broker: Binance USD-M Futures (Testnet by default) ---
    # Separate signup from the spot testnet: https://testnet.binancefuture.com
    binance_futures_api_key: str = ""
    binance_futures_secret_key: str = ""
    binance_futures_testnet: bool = True
    futures_leverage: int = 3           # low leverage; structure stops sit inside liquidation

    # --- Broker: Alpaca (optional alternative) ---
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    # Master safety switch for Alpaca. Default = paper (virtual money).
    live_trading: bool = False

    # --- AI signal ---
    # Gemini models compared on the accuracy leaderboard. The first available one
    # (or ``trading_model`` if set & available) is the model the bot actually trades on.
    gemini_models: list[str] = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    trading_model: str = ""            # "" -> use first available model

    # --- AI rate-limit handling (Gemini free tier) ---
    # The free tier rate-limits per-minute (429) and the model is sometimes
    # overloaded (503). We retry transient errors with exponential backoff and
    # space calls out so a burst of per-asset requests stays under the limit.
    gemini_max_retries: int = 5             # retry 429/5xx this many times before giving up
    gemini_retry_base_delay: float = 2.0    # backoff: ~2, 4, 8, 16, 32 s (+ jitter)
    gemini_retry_max_delay: float = 32.0    # cap a single backoff wait at this
    llm_min_interval_seconds: float = 6.0   # min spacing between model calls (RPM guard)
    gemini_models_cache_ttl: int = 21_600   # cache models.list() for 6 h (long-running run)

    # --- Storage ---
    # Local default = SQLite. In production set DATABASE_URL to the Supabase
    # Postgres connection string (postgresql://...).
    database_url: str = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"

    # --- News fetching ---
    news_limit: int = 15               # headlines fed to the model per asset
    news_lookback_days: int = 3

    # --- Order-flow strategy: timeframes + confluence tuning ---
    strategy_htf: str = "4h"            # higher timeframe = trend bias
    strategy_mtf: str = "1h"            # mid = structure / value / CVD
    strategy_ltf: str = "15m"           # low = sweep / trigger / decision cadence
    strategy_mode: str = "reversal"     # default setup style: "reversal" | "momentum"
    asset_modes: dict[str, str] = {}    # per-asset override, e.g. {"ETH": "momentum"}
    min_confluence: int = 5             # how many checklist items must pass (strict)
    strategy_trend_ema: int = 50        # HTF trend filter
    strategy_atr_period: int = 14
    strategy_atr_min_pct: float = 0.003  # skip dead volatility
    strategy_atr_max_pct: float = 0.08   # skip chaotic volatility
    strategy_overext_atr_mult: float = 4.0   # don't chase price far from the trend EMA
    strategy_reward_risk: float = 2.0    # take-profit = entry +/- RR * risk
    strategy_atr_stop_mult: float = 1.5  # fallback stop distance when no sweep level
    strategy_funding_cap: float = 0.0005  # |funding| above this crowds that side
    strategy_delta_strength_min: float = 0.15  # min |taker delta|/volume for order-flow check
    strategy_delta_lookback: int = 3     # candles for the delta-strength read
    strategy_cvd_lookback: int = 20      # bars for the CVD-slope read
    max_hold_bars: int = 96              # force-exit a position after this many LTF bars

    # --- Position sizing / risk ---
    risk_per_trade_pct: float = 0.005   # risk this fraction of equity per trade (~0.5%)
    max_position_pct: float = 0.10      # per-position notional cap (× leverage) of equity
    max_open_positions: int = 5         # cap concurrent open positions
    cash_buffer_pct: float = 0.10       # never deploy this fraction of margin
    allow_short: bool = True            # futures: take shorts as well as longs
    stop_loss_pct: float = 0.0          # fallback only (strategy sets structure stops)
    take_profit_pct: float = 0.0        # fallback only

    # --- Legacy news/LLM signal (kept for the optional accuracy leaderboard; the
    # trader no longer uses these — decisions come from the order-flow strategy) ---
    min_confidence: float = 75.0
    require_fresh_news: bool = True
    news_fresh_hours: int = 24
    scale_size_by_confidence: bool = False

    # --- Scheduler cadence (production = systemd `app.cli run` on the EU box) ---
    run_interval_minutes: int = 30      # order-flow strategy evaluates this often
    run_interval_hours: int = 2         # legacy (unused when run_interval_minutes set)

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key.strip())

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_binance(self) -> bool:
        return bool(self.binance_api_key.strip() and self.binance_secret_key.strip())

    @property
    def has_binance_futures(self) -> bool:
        return bool(
            self.binance_futures_api_key.strip() and self.binance_futures_secret_key.strip()
        )

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
