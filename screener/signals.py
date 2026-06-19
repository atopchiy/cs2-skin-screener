"""Signal computation.

Given an item's stored price history, derive the signals that drive the
opportunity board and alerts. Pure functions over data we already have ‑
no network here. Add new signal types as more data sources come online
(e.g. cross-market spread once a multi-market fetcher is wired in).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from sqlite3 import Row
from typing import Optional


@dataclass
class SignalConfig:
    history_window_days: int = 30
    min_history_points: int = 8
    price_below_avg_pct: float = 12.0
    price_above_avg_pct: float = 25.0
    volume_spike_multiple: float = 3.0


@dataclass
class ItemSignals:
    market_hash_name: str
    price: Optional[float] = None
    volume: Optional[int] = None
    window_avg_price: Optional[float] = None
    pct_vs_avg: Optional[float] = None        # +ve = above average (pricey), -ve = below (cheap)
    window_median_volume: Optional[float] = None
    volume_ratio: Optional[float] = None      # current volume / median window volume
    points: int = 0
    flags: list[str] = field(default_factory=list)  # e.g. ["BUY", "VOLUME_SPIKE"]

    @property
    def has_alert(self) -> bool:
        return bool(self.flags)

    def to_dict(self) -> dict:
        return {
            "market_hash_name": self.market_hash_name,
            "price": self.price,
            "volume": self.volume,
            "window_avg_price": round(self.window_avg_price, 4) if self.window_avg_price else None,
            "pct_vs_avg": round(self.pct_vs_avg, 1) if self.pct_vs_avg is not None else None,
            "window_median_volume": self.window_median_volume,
            "volume_ratio": round(self.volume_ratio, 2) if self.volume_ratio is not None else None,
            "points": self.points,
            "flags": self.flags,
        }


def _price_of(row: Row) -> Optional[float]:
    p = row["lowest_price"]
    return p if p is not None else row["median_price"]


def compute(market_hash_name: str, history: list[Row], cfg: SignalConfig) -> ItemSignals:
    """history is ASC by ts (oldest first), already windowed to the lookback."""
    sig = ItemSignals(market_hash_name=market_hash_name, points=len(history))
    if not history:
        return sig

    latest = history[-1]
    sig.price = _price_of(latest)
    sig.volume = latest["volume"]

    prices = [p for p in (_price_of(r) for r in history) if p is not None]
    volumes = [r["volume"] for r in history if r["volume"] is not None]

    # --- price vs window average ----------------------------------------
    if sig.price is not None and len(prices) >= cfg.min_history_points:
        baseline = prices[:-1] if len(prices) > 1 else prices  # exclude current point
        sig.window_avg_price = statistics.fmean(baseline)
        if sig.window_avg_price:
            sig.pct_vs_avg = (sig.price - sig.window_avg_price) / sig.window_avg_price * 100.0
            if sig.pct_vs_avg <= -cfg.price_below_avg_pct:
                sig.flags.append("BUY")
            elif sig.pct_vs_avg >= cfg.price_above_avg_pct:
                sig.flags.append("OVERHEATED")

    # --- volume spike ----------------------------------------------------
    if sig.volume is not None and len(volumes) >= cfg.min_history_points:
        baseline_vol = volumes[:-1] if len(volumes) > 1 else volumes
        med = statistics.median(baseline_vol)
        sig.window_median_volume = med
        if med and med > 0:
            sig.volume_ratio = sig.volume / med
            if sig.volume_ratio >= cfg.volume_spike_multiple:
                sig.flags.append("VOLUME_SPIKE")

    return sig
