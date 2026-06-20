"""CS2 Skin Screener — one poll cycle (multi-source).

  poll each enabled source -> store (source-tagged) -> assemble signals
  -> write dashboard -> send alerts

Sources: steam (volume), skinport (free cash market), csfloat (primary buy market).
CSFloat needs the CSFLOAT_API_KEY env var; if unset, csfloat is skipped.

Run locally:   python run.py
Flags:
  --no-fetch           skip fetching; recompute signals/dashboard from stored history
  --limit N            only poll the first N watchlist items (debugging)
  --sources a,b        override which sources to poll (debugging)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import yaml

from screener.alerts import send_alerts
from screener.dashboard import write_site
from screener.fetchers import get_fetcher
from screener.fetchers.base import RateLimited
from screener.signals import ArbitrageConfig, SignalConfig, assemble
from screener.storage import Storage

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "screener.db"
SITE_DIR = ROOT / "site"
STATE_PATH = ROOT / "data" / "alert_state.json"


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _build_fetcher(source: str, cfg: dict):
    common = {"appid": cfg.get("appid", 730), "currency": cfg.get("currency", 1)}
    if source == "csfloat":
        key = os.environ.get("CSFLOAT_API_KEY")
        if not key:
            print("[poll] csfloat: CSFLOAT_API_KEY not set; skipping source")
            return None
        return get_fetcher("csfloat", api_key=key, **common)
    return get_fetcher(source, **common)


def poll_source(source: str, cfg: dict, storage: Storage, watchlist: list[str], delay: float) -> int:
    fetcher = _build_fetcher(source, cfg)
    if fetcher is None:
        return 0
    recorded = 0
    for i, name in enumerate(watchlist):
        try:
            quote = fetcher.fetch(name)
        except RateLimited:
            print(f"[{source}] rate-limited at {name!r}; backing off 30s")
            time.sleep(30)
            try:
                quote = fetcher.fetch(name)
            except Exception as exc:  # noqa: BLE001
                print(f"[{source}] giving up on {name!r}: {exc}")
                quote = None
        except Exception as exc:  # noqa: BLE001
            print(f"[{source}] error on {name!r}: {exc}")
            quote = None

        if quote is not None and quote.price is not None:
            storage.record(quote)
            recorded += 1
        if delay and i < len(watchlist) - 1:
            time.sleep(delay)
    print(f"[{source}] recorded {recorded}/{len(watchlist)}")
    return recorded


def poll(cfg: dict, storage: Storage, limit: int | None = None,
         only_sources: list[str] | None = None) -> int:
    watchlist = cfg.get("watchlist", [])
    if limit:
        watchlist = watchlist[:limit]
    sources_cfg = cfg.get("sources", {})
    total = 0
    for source, scfg in sources_cfg.items():
        if only_sources is not None and source not in only_sources:
            continue
        if not (scfg or {}).get("enabled", False):
            continue
        delay = float((scfg or {}).get("poll_delay_seconds", 0))
        total += poll_source(source, cfg, storage, watchlist, delay)
    return total


def _signal_config(cfg: dict) -> SignalConfig:
    sc = cfg.get("signals", {})
    ac = sc.get("arbitrage", {})
    return SignalConfig(
        history_window_days=sc.get("history_window_days", 30),
        min_history_points=sc.get("min_history_points", 8),
        price_below_avg_pct=sc.get("price_below_avg_pct", 12.0),
        price_above_avg_pct=sc.get("price_above_avg_pct", 25.0),
        volume_spike_multiple=sc.get("volume_spike_multiple", 3.0),
        primary_price_source=sc.get("primary_price_source", "csfloat"),
        volume_source=sc.get("volume_source", "steam"),
        arbitrage=ArbitrageConfig(
            buy_source=ac.get("buy_source", "csfloat"),
            sell_source=ac.get("sell_source", "skinport"),
            sell_fee_pct=ac.get("sell_fee_pct", 12.0),
            min_net_margin_pct=ac.get("min_net_margin_pct", 5.0),
            min_abs_profit_usd=ac.get("min_abs_profit_usd", 1.0),
        ),
    )


def evaluate(cfg: dict, storage: Storage) -> list:
    scfg = _signal_config(cfg)
    results = []
    for name in cfg.get("watchlist", []):
        primary_hist = storage.history(name, since_days=scfg.history_window_days,
                                        source=scfg.primary_price_source)
        # Fall back to steam history for vs-avg if the primary has no data yet.
        if not primary_hist:
            primary_hist = storage.history(name, since_days=scfg.history_window_days, source="steam")
        volume_hist = storage.history(name, since_days=scfg.history_window_days,
                                      source=scfg.volume_source)
        latest_by_source = storage.latest_per_source(name)
        results.append(assemble(name, primary_hist, volume_hist, latest_by_source, scfg))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sources", help="comma-separated source override")
    args = ap.parse_args(argv)

    cfg = load_config()
    storage = Storage(DB_PATH)
    only = args.sources.split(",") if args.sources else None

    if not args.no_fetch:
        n = poll(cfg, storage, limit=args.limit, only_sources=only)
        print(f"[run] recorded {n} quotes total")

    signals = evaluate(cfg, storage)
    index = write_site(signals, SITE_DIR, currency=cfg.get("currency", 1))
    print(f"[run] dashboard -> {index}")

    sent = send_alerts(signals, state_path=STATE_PATH)
    print(f"[run] alerts sent: {sent}")

    storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
