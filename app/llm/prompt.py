"""Prompt construction + response normalization (provider-agnostic)."""
from __future__ import annotations

from app.config import Asset
from app.llm.base import PredictionResult
from app.sources.news import NewsItem

SYSTEM_INSTRUCTION = (
    "You are a financial markets analyst. Given recent news about an asset, "
    "estimate the probability that its price will go UP (bullish) versus DOWN "
    "(bearish) over the near term. Base your judgment on the provided news and "
    "sound market reasoning. Be calibrated and avoid always predicting up. "
    "Respond with strict JSON only."
)


def build_prompt(asset: Asset, news: list[NewsItem]) -> str:
    if news:
        lines = []
        for i, n in enumerate(news, 1):
            line = f"{i}. {n.headline}"
            if n.summary:
                line += f" — {n.summary[:300]}"
            if n.source:
                line += f" ({n.source})"
            lines.append(line)
        news_block = "\n".join(lines)
    else:
        news_block = "(No recent news available — rely on general reasoning.)"

    return (
        f"Asset: {asset.name} ({asset.symbol}), type: {asset.kind}.\n\n"
        f"Recent news:\n{news_block}\n\n"
        "Estimate the near-term price direction and return JSON with:\n"
        "- bullish_prob: number 0-100 (probability the price goes up)\n"
        "- bearish_prob: number 0-100 (probability the price goes down)\n"
        "- rationale: 1-3 sentence explanation grounded in the news above.\n"
        "bullish_prob + bearish_prob must sum to 100."
    )


SETUP_SYSTEM_INSTRUCTION = (
    "You are a disciplined crypto-futures trader reviewing a quantitative order-flow "
    "setup proposed by a deterministic strategy. Judge ONLY whether the setup is worth "
    "taking as described: weigh how many confluence checks passed, the trend/structure, "
    "order flow (CVD slope, taker delta), location versus value, funding and the "
    "reward:risk. Do not invent data beyond what is provided. Be calibrated and "
    "skeptical — reject weak or contradictory setups. Respond with strict JSON only."
)


def build_setup_prompt(asset: Asset, setup: dict) -> str:
    """Describe an order-flow setup (the ``ConfluenceResult`` breakdown) for the LLM."""
    direction = str(setup.get("direction", "")).upper()
    checks = setup.get("checks", {}) or {}
    checks_str = ", ".join(f"{'PASS' if v else 'FAIL'} {k}" for k, v in checks.items()) or "(none)"
    feats = setup.get("features", {}) or {}
    feat_keys = (
        "structure", "atr_pct", "vwap", "poc", "value_low", "value_high",
        "cvd", "cvd_slope", "delta_strength", "funding", "book_imbalance",
    )
    feats_str = ", ".join(
        f"{k}={feats[k]}" for k in feat_keys if feats.get(k) is not None
    ) or "(none)"
    return (
        f"Asset: {asset.name} ({asset.symbol}).\n"
        f"Proposed trade: {direction} ({setup.get('mode')} setup).\n"
        f"Confluence: {setup.get('confluence')} checks passed.\n"
        f"Checklist: {checks_str}.\n"
        f"Order flow / context: {feats_str}.\n"
        f"Entry: {setup.get('price')}  Stop: {setup.get('stop')}  Target: {setup.get('target')}.\n\n"
        "Judge whether THIS setup should be traded as proposed and return JSON with:\n"
        "- bullish_prob: number 0-100 (probability price goes up from here)\n"
        "- bearish_prob: number 0-100 (probability price goes down from here)\n"
        "- rationale: 1-2 sentence verdict naming the strongest / weakest factors.\n"
        "bullish_prob + bearish_prob must sum to 100. Endorse a LONG with a high "
        "bullish_prob, a SHORT with a high bearish_prob; stay near 50/50 if unconvinced."
    )


def parse_result(data: dict) -> PredictionResult:
    """Coerce a raw JSON dict into a normalized PredictionResult."""
    bullish = _to_float(data.get("bullish_prob"))
    bearish = _to_float(data.get("bearish_prob"))
    rationale = str(data.get("rationale", "") or "").strip()
    return _normalize(bullish, bearish, rationale)


def _to_float(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _normalize(bullish: float, bearish: float, rationale: str) -> PredictionResult:
    total = bullish + bearish
    if total <= 0:
        bullish, bearish = 50.0, 50.0
    else:
        bullish = round(bullish / total * 100, 1)
        bearish = round(100.0 - bullish, 1)
    return PredictionResult(bullish_prob=bullish, bearish_prob=bearish, rationale=rationale)
