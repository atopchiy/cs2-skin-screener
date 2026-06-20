"""Signal computation (multi-source).

Signals split by what they measure and which source is authoritative for it:
  * price-vs-history (BUY / OVERHEATED) -> the PRIMARY buy market (CSFloat)
  * volume spike (VOLUME_SPIKE)          -> Steam (only free 24h-units-sold feed)
  * cross-market spread (ARBITRAGE)      -> buy on buy_source, sell on sell_source

Pure functions over data we already have - no network. `compute()` (single
history) is kept for the backtester; `assemble()` is the live multi-source path.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from sqlite3 import Row
from typing import Optional


@dataclass
class ArbitrageConfig:
    buy_source: str = "csfloat"
    sell_source: str = "skinport"
    sell_fee_pct: float = 12.0        # marketplace cut on the sell side
    min_net_margin_pct: float = 5.0   # flag ARBITRAGE at/above this net margin %
    min_abs_profit_usd: float = 1.0   # AND at/above this absolute $ profit (kills penny spreads)


@dataclass
class SignalConfig:
    history_window_days: int = 30
    min_history_points: int = 8
    price_below_avg_pct: float = 12.0
    price_above_avg_pct: float = 25.0
    volume_spike_multiple: float = 3.0
    primary_price_source: str = "csfloat"  # vs-history anchor; falls back if absent
    volume_source: str = "steam"
    arbitrage: ArbitrageConfig = field(default_factory=ArbitrageConfig)


@dataclass
class ItemSignals:
    market_hash_name: str
    price: Optional[float] = None              # primary (buy) price
    price_source: Optional[str] = None
    prices: dict = field(default_factory=dict)  # source -> price (display)
    volume: Optional[int] = None               # steam 24h units sold
    window_avg_price: Optional[float] = None
    pct_vs_avg: Optional[float] = None
    window_median_volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    spread_pct: Optional[float] = None         # raw (sell-buy)/buy across markets
    net_margin_pct: Optional[float] = None     # after sell-side fee
    points: int = 0
    flags: list = field(default_factory=list)

    @property
    def has_alert(self) -> bool:
        return bool(self.flags)

    def to_dict(self) -> dict:
        r = lambda v, n=2: round(v, n) if v is not None else None
        return {
            "market_hash_name": self.market_hash_name,
            "price": self.price,
            "price_source": self.price_source,
            "prices": self.prices,
            "volume": self.volume,
            "window_avg_price": r(self.window_avg_price, 4),
            "pct_vs_avg": r(self.pct_vs_avg, 1),
            "window_median_volume": self.window_median_volume,
            "volume_ratio": r(self.volume_ratio),
            "spread_pct": r(self.spread_pct, 1),
            "net_margin_pct": r(self.net_margin_pct, 1),
            "points": self.points,
            "flags": self.flags,
        }


def _price_of(row: Row) -> Optional[float]:
    p = row["lowest_price"]
    return p if p is not None else row["median_price"]


def _price_signal(history: list[Row], cfg: SignalConfig):
    """Returns (price, window_avg, pct_vs_avg, flags)."""
    flags: list[str] = []
    if not history:
        return None, None, None, flags
    price = _price_of(history[-1])
    prices = [p for p in (_price_of(r) for r in history) if p is not None]
    window_avg = pct = None
    if price is not None and len(prices) >= cfg.min_history_points:
        baseline = prices[:-1] if len(prices) > 1 else prices
        window_avg = statistics.fmean(baseline)
        if window_avg:
            pct = (price - window_avg) / window_avg * 100.0
            if pct <= -cfg.price_below_avg_pct:
                flags.append("BUY")
            elif pct >= cfg.price_above_avg_pct:
                flags.append("OVERHEATED")
    return price, window_avg, pct, flags


def _volume_signal(history: list[Row], cfg: SignalConfig):
    """Returns (volume, window_median_vol, volume_ratio, flags)."""
    flags: list[str] = []
    if not history:
        return None, None, None, flags
    volume = history[-1]["volume"]
    volumes = [r["volume"] for r in history if r["volume"] is not None]
    med = ratio = None
    if volume is not None and len(volumes) >= cfg.min_history_points:
        baseline = volumes[:-1] if len(volumes) > 1 else volumes
        med = statistics.median(baseline)
        if med and med > 0:
            ratio = volume / med
            if ratio >= cfg.volume_spike_multiple:
                flags.append("VOLUME_SPIKE")
    return volume, med, ratio, flags


def compute(market_hash_name: str, history: list[Row], cfg: SignalConfig) -> ItemSignals:
    """Single-source signal (price+volume on the same history). Used by backtester."""
    sig = ItemSignals(market_hash_name=market_hash_name, points=len(history))
    price, avg, pct, pflags = _price_signal(history, cfg)
    vol, med, ratio, vflags = _volume_signal(history, cfg)
    sig.price, sig.window_avg_price, sig.pct_vs_avg = price, avg, pct
    sig.volume, sig.window_median_volume, sig.volume_ratio = vol, med, ratio
    sig.flags = pflags + vflags
    return sig


def assemble(
    market_hash_name: str,
    primary_history: list[Row],
    volume_history: list[Row],
    latest_by_source: dict,
    cfg: SignalConfig,
) -> ItemSignals:
    """Live multi-source signal."""
    sig = ItemSignals(market_hash_name=market_hash_name, points=len(primary_history))

    # Per-source display prices.
    for src, row in latest_by_source.items():
        p = _price_of(row)
        if p is not None:
            sig.prices[src] = p

    # Price-vs-history on the primary (buy) market.
    price, avg, pct, pflags = _price_signal(primary_history, cfg)
    sig.price = price
    sig.price_source = cfg.primary_price_source if price is not None else None
    sig.window_avg_price, sig.pct_vs_avg = avg, pct

    # Volume from Steam.
    vol, med, ratio, vflags = _volume_signal(volume_history, cfg)
    sig.volume, sig.window_median_volume, sig.volume_ratio = vol, med, ratio

    # Cross-market spread / arbitrage.
    ac = cfg.arbitrage
    buy = sig.prices.get(ac.buy_source)
    sell = sig.prices.get(ac.sell_source)
    aflags: list[str] = []
    if buy and sell and buy > 0:
        sig.spread_pct = (sell - buy) / buy * 100.0
        net_sell = sell * (1 - ac.sell_fee_pct / 100.0)
        abs_profit = net_sell - buy
        sig.net_margin_pct = abs_profit / buy * 100.0
        if sig.net_margin_pct >= ac.min_net_margin_pct and abs_profit >= ac.min_abs_profit_usd:
            aflags.append("ARBITRAGE")

    sig.flags = pflags + vflags + aflags
    return sig
