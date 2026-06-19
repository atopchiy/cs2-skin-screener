"""CS2 Skin Screener — one poll cycle.

  poll watchlist -> store -> compute signals -> write dashboard -> send alerts

Run locally:   python run.py
In CI:         invoked by .github/workflows/poll.yml on a cron schedule.

Flags:
  --once-item "Name"   fetch a single item (debugging)
  --no-fetch           skip fetching; just recompute signals/dashboard from stored history
  --limit N            only poll the first N watchlist items (debugging)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from screener.alerts import send_alerts
from screener.dashboard import write_site
from screener.fetchers import get_fetcher
from screener.fetchers.base import RateLimited
from screener.signals import SignalConfig, compute
from screener.storage import Storage

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "screener.db"
SITE_DIR = ROOT / "site"
STATE_PATH = ROOT / "data" / "alert_state.json"


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def poll(cfg: dict, storage: Storage, limit: int | None = None) -> int:
    fetcher = get_fetcher(
        cfg.get("fetcher", "steam"),
        appid=cfg.get("appid", 730),
        currency=cfg.get("currency", 1),
    )
    delay = float(cfg.get("poll_delay_seconds", 3.5))
    watchlist = cfg.get("watchlist", [])
    if limit:
        watchlist = watchlist[:limit]

    recorded = 0
    for i, name in enumerate(watchlist):
        try:
            quote = fetcher.fetch(name)
        except RateLimited:
            print(f"[poll] rate-limited at {name!r}; backing off 30s")
            time.sleep(30)
            try:
                quote = fetcher.fetch(name)
            except Exception as exc:  # noqa: BLE001
                print(f"[poll] giving up on {name!r}: {exc}")
                quote = None
        except Exception as exc:  # noqa: BLE001
            print(f"[poll] error on {name!r}: {exc}")
            quote = None

        if quote is not None:
            storage.record(quote)
            recorded += 1
            print(f"[poll] {name}: price={quote.price} vol={quote.volume}")
        else:
            print(f"[poll] {name}: no data")

        if i < len(watchlist) - 1:
            time.sleep(delay)
    return recorded


def evaluate(cfg: dict, storage: Storage) -> list:
    sc = cfg.get("signals", {})
    scfg = SignalConfig(
        history_window_days=sc.get("history_window_days", 30),
        min_history_points=sc.get("min_history_points", 8),
        price_below_avg_pct=sc.get("price_below_avg_pct", 12.0),
        price_above_avg_pct=sc.get("price_above_avg_pct", 25.0),
        volume_spike_multiple=sc.get("volume_spike_multiple", 3.0),
    )
    results = []
    for name in cfg.get("watchlist", []):
        hist = storage.history(name, since_days=scfg.history_window_days)
        results.append(compute(name, hist, scfg))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once-item")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    cfg = load_config()
    storage = Storage(DB_PATH)

    if args.once_item:
        cfg["watchlist"] = [args.once_item]

    if not args.no_fetch:
        n = poll(cfg, storage, limit=args.limit)
        print(f"[run] recorded {n} quotes")

    signals = evaluate(cfg, storage)
    index = write_site(signals, SITE_DIR, currency=cfg.get("currency", 1))
    print(f"[run] dashboard -> {index}")

    sent = send_alerts(signals, state_path=STATE_PATH)
    print(f"[run] alerts sent: {sent}")

    storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
