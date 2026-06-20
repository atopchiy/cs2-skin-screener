"""Run the signal backtester over accumulated history.

  python backtest.py                 # default horizons 7/14/30 days
  python backtest.py --horizons 3 7  # custom horizons (days)

Writes data/backtest.json and prints a readable report. Safe to run anytime;
with little history it reports small/zero sample sizes honestly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from screener.backtest import backtest, format_report
from screener.signals import SignalConfig
from screener.storage import Storage

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "screener.db"
OUT_PATH = ROOT / "data" / "backtest.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", type=float, nargs="+", default=[7, 14, 30])
    args = ap.parse_args(argv)

    cfg_raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sc = cfg_raw.get("signals", {})
    scfg = SignalConfig(
        history_window_days=sc.get("history_window_days", 30),
        min_history_points=sc.get("min_history_points", 8),
        price_below_avg_pct=sc.get("price_below_avg_pct", 12.0),
        price_above_avg_pct=sc.get("price_above_avg_pct", 25.0),
        volume_spike_multiple=sc.get("volume_spike_multiple", 3.0),
        primary_price_source=sc.get("primary_price_source", "csfloat"),
    )

    storage = Storage(DB_PATH)
    result = backtest(storage, scfg, cfg_raw.get("watchlist", []), tuple(args.horizons))
    storage.close()

    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(format_report(result))
    print(f"\n[backtest] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
