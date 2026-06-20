"""SQLite storage for price history.

The accumulated history IS the asset of this project, so the schema is kept
simple and append-only. Swappable for Postgres later (same query shapes).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .fetchers.base import PriceQuote

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    market_hash_name TEXT PRIMARY KEY,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT NOT NULL,
    ts               TEXT NOT NULL,          -- ISO-8601 UTC
    source           TEXT NOT NULL,
    currency         INTEGER NOT NULL,
    lowest_price     REAL,
    median_price     REAL,
    volume           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_price_name_ts
    ON price_history (market_hash_name, ts);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- writes -------------------------------------------------------------
    def record(self, quote: PriceQuote, ts: Optional[str] = None) -> None:
        ts = ts or utcnow_iso()
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO items (market_hash_name, first_seen, last_seen)
               VALUES (?, ?, ?)
               ON CONFLICT(market_hash_name) DO UPDATE SET last_seen=excluded.last_seen""",
            (quote.market_hash_name, ts, ts),
        )
        cur.execute(
            """INSERT INTO price_history
               (market_hash_name, ts, source, currency, lowest_price, median_price, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                quote.market_hash_name,
                ts,
                quote.source,
                quote.currency,
                quote.lowest_price,
                quote.median_price,
                quote.volume,
            ),
        )
        self.conn.commit()

    # -- reads --------------------------------------------------------------
    def history(
        self,
        market_hash_name: str,
        since_days: Optional[int] = None,
        source: Optional[str] = None,
    ) -> list[sqlite3.Row]:
        q = "SELECT * FROM price_history WHERE market_hash_name = ?"
        params: list = [market_hash_name]
        if source is not None:
            q += " AND source = ?"
            params.append(source)
        if since_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat(timespec="seconds")
            q += " AND ts >= ?"
            params.append(cutoff)
        q += " ORDER BY ts ASC"
        return self.conn.execute(q, params).fetchall()

    def latest(self, market_hash_name: str, source: Optional[str] = None) -> Optional[sqlite3.Row]:
        q = "SELECT * FROM price_history WHERE market_hash_name = ?"
        params: list = [market_hash_name]
        if source is not None:
            q += " AND source = ?"
            params.append(source)
        q += " ORDER BY ts DESC LIMIT 1"
        return self.conn.execute(q, params).fetchone()

    def latest_per_source(self, market_hash_name: str) -> dict[str, sqlite3.Row]:
        """Most-recent row for each source that has data for this item."""
        rows = self.conn.execute(
            "SELECT * FROM price_history WHERE market_hash_name = ? ORDER BY ts ASC",
            (market_hash_name,),
        ).fetchall()
        out: dict[str, sqlite3.Row] = {}
        for r in rows:  # ASC, so last write per source wins
            out[r["source"]] = r
        return out

    def all_items(self) -> list[str]:
        rows = self.conn.execute("SELECT market_hash_name FROM items ORDER BY market_hash_name").fetchall()
        return [r["market_hash_name"] for r in rows]
