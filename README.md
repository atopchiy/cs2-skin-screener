# CS2 Skin Screener

A free, serverless screener for the CS2 skin market. On a schedule it polls
prices, accumulates history, computes buy/sell/volume signals, publishes a
static dashboard to GitHub Pages, and pings you on Telegram when something
crosses a threshold.

It is a **discipline-and-coverage tool**, not an oracle: its edge is watching
everything consistently and applying your rules without forgetting them — not
predicting Valve updates or pricing rare collector patterns.

## How it works

```
 GitHub Actions cron (every 30 min)
   └─ run.py
        ├─ fetch    watchlist prices            (screener/fetchers/steam.py)
        ├─ store    append to SQLite history    (screener/storage.py)
        ├─ signal   price-vs-avg, volume spike  (screener/signals.py)
        ├─ site     write static dashboard      (screener/dashboard.py) -> Pages
        └─ alert    Telegram on fresh signals   (screener/alerts.py)
   └─ commit updated data/screener.db back to the repo (git-scraper persistence)
```

## Signals (current)

| Flag           | Fires when                                                        |
|----------------|-------------------------------------------------------------------|
| `BUY`          | current price is ≥ `price_below_avg_pct` below its window average  |
| `OVERHEATED`   | current price is ≥ `price_above_avg_pct` above its window average  |
| `VOLUME_SPIKE` | 24h volume ≥ `volume_spike_multiple` × the window-median volume    |

Signals only fire once an item has `min_history_points` samples, so they warm
up over the first few hours/days of polling. Thresholds live in `config.yaml`.

## Local use

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
python run.py                 # full poll cycle
python run.py --limit 3       # poll only first 3 items (quick test)
python run.py --no-fetch      # recompute signals/dashboard from stored history
```

Open `site/index.html` to view the dashboard locally.

## Deploy (free)

1. Create a repo on your **personal** GitHub and push this project.
2. Settings → Pages → Source = **GitHub Actions**.
3. (Optional) Telegram alerts: create a bot via @BotFather, then add repo
   secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. The `poll-and-publish` workflow runs every 30 min and on manual dispatch.

## Roadmap / upgrade paths

- **Cross-market arbitrage signal** — drop in a Pricempire/CSPriceAPI fetcher
  (implements the same `Fetcher` interface) to get Buff/Skinport prices and flag
  spread opportunities. Most immediately monetizable signal.
- **Supply/lifecycle signal** — tag cases by drop-pool status (active / rare /
  discontinued) for the structural case-investing thesis.
- **Float & pattern data** — CSFloat fetcher for wear/pattern-level pricing.
- **Backtester** — replay stored history to score each signal's historical
  hit-rate (the credibility layer). Build before trusting any signal with money.
- **Postgres** — when the committed SQLite history gets large, move to a free
  Neon/Supabase Postgres (storage layer is intentionally swappable).
