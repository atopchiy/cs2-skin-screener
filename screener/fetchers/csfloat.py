"""CSFloat marketplace fetcher — the primary BUY-price anchor.

Needs a free API key (CSFloat profile -> Developer). Per-item query:
  GET https://csfloat.com/api/v1/listings
      ?limit=1&sort_by=lowest_price&type=buy_now&market_hash_name=<name>
  Header: Authorization: <api_key>

Prices are in CENTS. The cheapest buy_now listing is our lowest_price; the
listing's `reference` block also gives base_price (CSFloat market reference)
and quantity (listings = liquidity), so one call yields price + reference + qty.

No bulk endpoint and the API is rate-limited, so this paces slower than Steam/
Skinport — run it on a longer cadence if needed.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .base import PriceQuote, RateLimited

_URL = "https://csfloat.com/api/v1/listings"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _cents(v) -> Optional[float]:
    return round(v / 100.0, 2) if isinstance(v, (int, float)) else None


class CSFloatFetcher:
    name = "csfloat"

    def __init__(self, api_key: str, appid: int = 730, currency: int = 1,
                 timeout: float = 20.0, retries: int = 2,
                 session: Optional[requests.Session] = None) -> None:
        if not api_key:
            raise ValueError("CSFloatFetcher requires an api_key")
        self.api_key = api_key
        self.appid = appid
        self.currency = currency
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept": "application/json",
            "Authorization": api_key,
        })

    def fetch(self, market_hash_name: str) -> Optional[PriceQuote]:
        params = {
            "limit": 1,
            "sort_by": "lowest_price",
            "type": "buy_now",
            "market_hash_name": market_hash_name,
        }
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2.0 * (attempt + 1))
                continue

            if resp.status_code == 429:
                raise RateLimited(f"429 for {market_hash_name!r}")
            if resp.status_code >= 500:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(2.0 * (attempt + 1))
                continue
            resp.raise_for_status()

            try:
                data = resp.json()
            except ValueError:
                return None

            listings = data.get("data") if isinstance(data, dict) else data
            if not listings:
                return None

            top = listings[0]
            ref = top.get("reference") or {}
            return PriceQuote(
                market_hash_name=market_hash_name,
                source=self.name,
                currency=self.currency,
                lowest_price=_cents(top.get("price")),
                median_price=_cents(ref.get("base_price")),  # CSFloat market reference
                volume=ref.get("quantity"),                  # listings = liquidity proxy
            )

        if last_exc:
            raise last_exc
        return None
