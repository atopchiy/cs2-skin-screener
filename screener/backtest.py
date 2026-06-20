"""Backtester — score each signal's historical hit-rate on stored history.

Idea: walk every item's price history chronologically. At each point, recompute
the signal *as it would have looked then* (using only data up to that point),
detect the rising edge of each flag (the moment it newly fires), then look
forward `horizon` days and measure the realized return from that entry price.

Win definition is direction-aware:
  BUY          -> win if forward return  > 0     (we expected price to recover/rise)
  OVERHEATED   -> win if forward return  < 0     (we expected price to fall)
  VOLUME_SPIKE -> directionless; we just report the return distribution

This is what turns the screener from "a board of flags" into "flags you know
whether to trust." With little history it will honestly report small/zero
sample sizes rather than pretend.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sqlite3 import Row
from typing import Optional

from .signals import SignalConfig, compute
from .storage import Storage

# Signal -> sign we're betting on (+1 expect up, -1 expect down, 0 directionless)
_DIRECTION = {"BUY": +1, "OVERHEATED": -1, "VOLUME_SPIKE": 0}


def _ts(row: Row) -> datetime:
    return datetime.fromisoformat(row["ts"])


def _price(row: Row) -> Optional[float]:
    p = row["lowest_price"]
    return p if p is not None else row["median_price"]


def _forward_price(history: list[Row], i: int, horizon_days: float) -> Optional[float]:
    """First price at/after history[i].ts + horizon_days."""
    target = _ts(history[i]) + timedelta(days=horizon_days)
    for j in range(i + 1, len(history)):
        if _ts(history[j]) >= target:
            return _price(history[j])
    return None


@dataclass
class HorizonStats:
    horizon_days: float
    n: int = 0
    wins: int = 0
    returns: list[float] = field(default_factory=list)

    def add(self, ret: float, win: bool) -> None:
        self.n += 1
        self.returns.append(ret)
        if win:
            self.wins += 1

    def summary(self) -> dict:
        return {
            "horizon_days": self.horizon_days,
            "n": self.n,
            "win_rate": round(self.wins / self.n, 3) if self.n else None,
            "median_return_pct": round(statistics.median(self.returns) * 100, 2) if self.returns else None,
            "mean_return_pct": round(statistics.fmean(self.returns) * 100, 2) if self.returns else None,
        }


def backtest(
    storage: Storage,
    cfg: SignalConfig,
    watchlist: list[str],
    horizons_days: tuple[float, ...] = (7, 14, 30),
    source: Optional[str] = None,
) -> dict:
    # flag -> horizon -> HorizonStats
    stats: dict[str, dict[float, HorizonStats]] = {
        flag: {h: HorizonStats(h) for h in horizons_days} for flag in _DIRECTION
    }
    source = source or cfg.primary_price_source

    for name in watchlist:
        full = storage.history(name, source=source)  # one source, ASC
        if len(full) < cfg.min_history_points + 1:
            continue

        prev_flags: set[str] = set()
        for i in range(len(full)):
            # Window = points within history_window_days up to and including i.
            cutoff = _ts(full[i]) - timedelta(days=cfg.history_window_days)
            window = [r for r in full[: i + 1] if _ts(r) >= cutoff]
            sig = compute(name, window, cfg)
            now_flags = set(sig.flags)

            # rising edges only (newly-fired flags this step)
            new_flags = now_flags - prev_flags
            prev_flags = now_flags
            if not new_flags:
                continue

            entry = _price(full[i])
            if not entry:
                continue

            for flag in new_flags:
                direction = _DIRECTION[flag]
                for h in horizons_days:
                    fwd = _forward_price(full, i, h)
                    if fwd is None:
                        continue  # not enough forward data yet
                    ret = (fwd - entry) / entry
                    if direction > 0:
                        win = ret > 0
                    elif direction < 0:
                        win = ret < 0
                    else:
                        win = ret > 0  # report, but treat up as "win" for display
                    stats[flag][h].add(ret, win)

    return {
        "config": {
            "source": source,
            "history_window_days": cfg.history_window_days,
            "min_history_points": cfg.min_history_points,
            "horizons_days": list(horizons_days),
        },
        "signals": {
            flag: [stats[flag][h].summary() for h in horizons_days] for flag in _DIRECTION
        },
    }


def format_report(result: dict) -> str:
    lines = ["=== Backtest report ===", f"config: {result['config']}", ""]
    any_data = False
    for flag, rows in result["signals"].items():
        lines.append(f"[{flag}]")
        for r in rows:
            if r["n"]:
                any_data = True
                lines.append(
                    f"  {int(r['horizon_days']):>3}d  n={r['n']:<4} "
                    f"win={r['win_rate']:<5} "
                    f"median={r['median_return_pct']}%  mean={r['mean_return_pct']}%"
                )
            else:
                lines.append(f"  {int(r['horizon_days']):>3}d  (no completed signals yet)")
        lines.append("")
    if not any_data:
        lines.append("No signal events with completed forward windows yet -- let history accumulate.")
    return "\n".join(lines)
