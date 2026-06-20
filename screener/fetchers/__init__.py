"""Pluggable price fetchers.

Each fetcher takes a Steam market_hash_name and returns a PriceQuote (or None).
The rest of the system only depends on the PriceQuote shape, so swapping
Steam for a paid multi-market aggregator (Pricempire, CSFloat, ...) later is a
drop-in change.
"""
from .base import Fetcher, PriceQuote
from .csfloat import CSFloatFetcher
from .skinport import SkinportFetcher
from .steam import SteamFetcher


def get_fetcher(name: str, **kwargs) -> Fetcher:
    name = (name or "steam").lower()
    if name == "steam":
        return SteamFetcher(**kwargs)
    if name == "skinport":
        return SkinportFetcher(**kwargs)
    if name == "csfloat":
        return CSFloatFetcher(**kwargs)
    raise ValueError(f"Unknown fetcher: {name!r}")


__all__ = [
    "Fetcher", "PriceQuote", "get_fetcher",
    "SteamFetcher", "SkinportFetcher", "CSFloatFetcher",
]
