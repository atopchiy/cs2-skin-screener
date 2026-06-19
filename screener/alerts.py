"""Telegram alerting.

Configured via env vars (set as GitHub Actions secrets in CI):
  TELEGRAM_BOT_TOKEN  - from @BotFather
  TELEGRAM_CHAT_ID    - your chat/channel id

If either is missing, alerting is a no-op (so local runs don't fail). To avoid
re-alerting the same condition every run, we keep a small state file of
already-sent (item, flag) pairs keyed by a coarse price bucket.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

import requests

from .signals import ItemSignals

_API = "https://api.telegram.org/bot{token}/sendMessage"


def _fmt(s: ItemSignals, currency_symbol: str = "$") -> str:
    price = f"{currency_symbol}{s.price:,.2f}" if s.price is not None else "—"
    parts = [f"<b>{', '.join(s.flags)}</b>  {s.market_hash_name}", f"price {price}"]
    if s.pct_vs_avg is not None:
        parts.append(f"{s.pct_vs_avg:+.1f}% vs avg")
    if s.volume is not None:
        parts.append(f"vol {s.volume:,}")
    if s.volume_ratio is not None:
        parts.append(f"({s.volume_ratio:.1f}x)")
    return " · ".join(parts)


def _dedup_key(s: ItemSignals) -> str:
    # Bucket price to ~5% so small wiggles don't re-alert, but a fresh move does.
    bucket = round(s.price / max(s.price * 0.05, 0.01)) if s.price else 0
    return f"{s.market_hash_name}|{','.join(sorted(s.flags))}|{bucket}"


def send_alerts(
    signals: Iterable[ItemSignals],
    state_path: str | Path = "data/alert_state.json",
    currency_symbol: str = "$",
) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    alerting = [s for s in signals if s.has_alert]
    if not alerting:
        return 0

    state_path = Path(state_path)
    try:
        sent = set(json.loads(state_path.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        sent = set()

    fresh = [s for s in alerting if _dedup_key(s) not in sent]
    if not fresh:
        return 0

    if not token or not chat_id:
        print(f"[alerts] {len(fresh)} new signal(s) but TELEGRAM_* not set; skipping send.")
        for s in fresh:
            print("   ", _fmt(s, currency_symbol))
        return 0

    text = "🟢 <b>CS2 Screener signals</b>\n\n" + "\n".join(_fmt(s, currency_symbol) for s in fresh)
    resp = requests.post(
        _API.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    resp.raise_for_status()

    for s in fresh:
        sent.add(_dedup_key(s))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(sent)), encoding="utf-8")
    return len(fresh)
