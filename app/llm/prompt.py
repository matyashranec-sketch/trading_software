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
