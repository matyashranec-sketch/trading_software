import httpx
import pytest
import respx

from app.config import Asset, Settings
from app.sources import news, prices

STOCK = Asset("TSLA", "Tesla", "stock")
BTC = Asset("BTC", "Bitcoin", "crypto", coingecko_id="bitcoin")


def _with_key(monkeypatch, module):
    monkeypatch.setattr(module, "get_settings", lambda: Settings(finnhub_api_key="test"))


@respx.mock
def test_finnhub_price(monkeypatch):
    _with_key(monkeypatch, prices)
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 250.5})
    )
    assert prices.fetch_price(STOCK) == 250.5


@respx.mock
def test_finnhub_price_missing_raises(monkeypatch):
    _with_key(monkeypatch, prices)
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 0})
    )
    with pytest.raises(prices.PriceUnavailable):
        prices.fetch_price(STOCK)


@respx.mock
def test_coingecko_price():
    respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
        return_value=httpx.Response(200, json={"bitcoin": {"usd": 65000}})
    )
    assert prices.fetch_price(BTC) == 65000.0


@respx.mock
def test_company_news_sorted_newest_first(monkeypatch):
    _with_key(monkeypatch, news)
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=[
            {"headline": "Older", "datetime": 2, "summary": "s", "source": "src", "url": "u"},
            {"headline": "Newer", "datetime": 5},
            {"headline": "", "datetime": 9},  # dropped (no headline)
        ])
    )
    items = news.fetch_news(STOCK)
    assert [i.headline for i in items] == ["Newer", "Older"]


def test_news_empty_without_key(monkeypatch):
    monkeypatch.setattr(news, "get_settings", lambda: Settings(finnhub_api_key=""))
    assert news.fetch_news(STOCK) == []
