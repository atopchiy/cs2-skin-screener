"""Steam Community Market priceoverview fetcher.

Free, no API key. Endpoint:
  https://steamcommunity.com/market/priceoverview/?appid=730&currency=1&market_hash_name=<name>

Returns e.g.:
  {"success": true, "lowest_price": "$0.42", "median_price": "$0.41", "volume": "4,219"}

Caveats:
  - Heavily rate-limited per IP. Space requests out (config: poll_delay_seconds).
  - `volume` is units sold in the last 24h, present only for liquid items.
  - Prices are localized strings; we parse USD ($1,234.56) here. Other currencies
    that use comma-as-decimal would need a locale-aware parse.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests

from .base import PriceQuote, RateLimited

_URL = "https://steamcommunity.com/market/priceoverview/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_NUM_RE = re.compile(r"[\d,.]+")


def _parse_price(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    # USD: comma is the thousands separator, dot is the decimal point.
    num = m.group(0).replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None


def _parse_volume(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


class SteamFetcher:
    name = "steam"

    def __init__(
        self,
        appid: int = 730,
        currency: int = 1,
        timeout: float = 15.0,
        retries: int = 2,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.appid = appid
        self.currency = currency
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": _UA, "Accept": "application/json"})

    def fetch(self, market_hash_name: str) -> Optional[PriceQuote]:
        params = {
            "appid": self.appid,
            "currency": self.currency,
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

            if not data or not data.get("success"):
                return None

            return PriceQuote(
                market_hash_name=market_hash_name,
                source=self.name,
                currency=self.currency,
                lowest_price=_parse_price(data.get("lowest_price")),
                median_price=_parse_price(data.get("median_price")),
                volume=_parse_volume(data.get("volume")),
            )

        if last_exc:
            raise last_exc
        return None
