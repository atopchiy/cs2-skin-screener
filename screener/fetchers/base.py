"""Fetcher interface + the common price-quote shape everything else depends on."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class PriceQuote:
    """A single point-in-time price observation for one item from one source."""
    market_hash_name: str
    source: str
    currency: int
    lowest_price: Optional[float]   # cheapest current listing
    median_price: Optional[float]   # median of recent sales
    volume: Optional[int]           # units sold in the last 24h (liquidity proxy)

    @property
    def price(self) -> Optional[float]:
        """Preferred single price: lowest listing, falling back to median."""
        return self.lowest_price if self.lowest_price is not None else self.median_price


class RateLimited(Exception):
    """Raised by a fetcher when the upstream returns HTTP 429."""


@runtime_checkable
class Fetcher(Protocol):
    name: str

    def fetch(self, market_hash_name: str) -> Optional[PriceQuote]:
        """Return a PriceQuote, or None if the item is unknown / has no data."""
        ...
