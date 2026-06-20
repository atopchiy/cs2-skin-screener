"""Skinport public items API fetcher.

Free, no key. One call returns ALL ~24.6k items, so we fetch once and cache,
then serve per-item lookups from memory. Endpoint:
  https://api.skinport.com/v1/items?app_id=730&currency=USD

Per item: min_price, max_price, mean_price, median_price, quantity (listings).
Rate-limited ~8 req / 5 min, so the bulk-once approach is essential.

Note: Skinport `quantity` is *listings available* (a supply/liquidity proxy),
NOT 24h units sold like Steam volume — different meaning, same field slot.
"""
from __future__ import annotations

from typing import Optional

import requests

from .base import PriceQuote

_URL = "https://api.skinport.com/v1/items"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SkinportFetcher:
    name = "skinport"

    def __init__(self, appid: int = 730, currency: int = 1, timeout: float = 40.0,
                 session: Optional[requests.Session] = None) -> None:
        self.appid = appid
        self.currency = currency
        self.timeout = timeout
        self.session = session or requests.Session()
        # Skinport REQUIRES Brotli; it 406s on gzip/identity. requests needs the
        # `brotli` package (in requirements.txt) to decode the response.
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept": "application/json",
            "Accept-Encoding": "br",
        })
        self._cache: Optional[dict[str, dict]] = None

    def _prime(self) -> None:
        resp = self.session.get(
            _URL,
            params={"app_id": self.appid, "currency": "USD"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._cache = {
            it["market_hash_name"]: it
            for it in data
            if it.get("market_hash_name")
        }

    def fetch(self, market_hash_name: str) -> Optional[PriceQuote]:
        if self._cache is None:
            self._prime()
        assert self._cache is not None
        it = self._cache.get(market_hash_name)
        if not it:
            return None
        return PriceQuote(
            market_hash_name=market_hash_name,
            source=self.name,
            currency=self.currency,
            lowest_price=it.get("min_price"),
            median_price=it.get("median_price"),
            volume=it.get("quantity"),  # listings available (supply proxy)
        )
