"""Generate the static dashboard (index.html + data.json) into an output dir.

GitHub Actions publishes this dir to GitHub Pages each run, so the dashboard is
always-up and free with no web server. Self-contained: embeds the data and
renders a sortable opportunity board client-side.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .signals import ItemSignals
from .storage import utcnow_iso

_FLAG_COLORS = {
    "BUY": "#1a7f37",
    "OVERHEATED": "#cf222e",
    "VOLUME_SPIKE": "#9a6700",
    "ARBITRAGE": "#8250df",
}


def _rank_key(s: ItemSignals):
    # Alerting items first; within those, best arbitrage margin then most-below-avg.
    alert_rank = 0 if s.has_alert else 1
    margin = -(s.net_margin_pct or 0)
    pct = s.pct_vs_avg if s.pct_vs_avg is not None else 0.0
    return (alert_rank, margin, pct)


def _money(v) -> str:
    return "—" if v is None else f"${v:,.2f}"


def write_site(signals: Iterable[ItemSignals], out_dir: str | Path, currency: int = 1) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = sorted(signals, key=_rank_key)
    generated = utcnow_iso()

    payload = {"generated": generated, "currency": currency, "items": [s.to_dict() for s in rows]}
    (out / "data.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    body_rows = []
    for s in rows:
        flags = "".join(
            f'<span class="flag" style="background:{_FLAG_COLORS.get(f, "#57606a")}">{f}</span>'
            for f in s.flags
        )
        pct = "" if s.pct_vs_avg is None else f"{s.pct_vs_avg:+.1f}%"
        pct_cls = "" if s.pct_vs_avg is None else ("neg" if s.pct_vs_avg < 0 else "pos")
        margin = "" if s.net_margin_pct is None else f"{s.net_margin_pct:+.1f}%"
        margin_cls = "" if s.net_margin_pct is None else ("pos2" if s.net_margin_pct > 0 else "neg2")
        vol = "—" if s.volume is None else f"{s.volume:,}"
        body_rows.append(
            "<tr>"
            f"<td class='name'>{_esc(s.market_hash_name)}</td>"
            f"<td class='num'>{_money(s.prices.get('csfloat'))}</td>"
            f"<td class='num'>{_money(s.prices.get('skinport'))}</td>"
            f"<td class='num'>{_money(s.prices.get('steam'))}</td>"
            f"<td class='num {pct_cls}'>{pct}</td>"
            f"<td class='num {margin_cls}'>{margin}</td>"
            f"<td class='num'>{vol}</td>"
            f"<td class='num'>{s.points}</td>"
            f"<td>{flags}</td>"
            "</tr>"
        )

    html = _TEMPLATE.format(
        generated=generated,
        rowcount=len(rows),
        alertcount=sum(1 for s in rows if s.has_alert),
        rows="\n".join(body_rows),
    )
    index = out / "index.html"
    index.write_text(html, encoding="utf-8")
    return index


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CS2 Skin Screener</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
         background: #0d1117; color: #e6edf3; }}
  header {{ padding: 20px 24px; border-bottom: 1px solid #21262d; }}
  h1 {{ margin: 0 0 4px; font-size: 20px; }}
  .meta {{ color: #8b949e; font-size: 13px; }}
  .legend {{ color: #8b949e; font-size: 12px; margin-top: 8px; }}
  .wrap {{ overflow-x: auto; padding: 16px 24px 48px; }}
  table {{ border-collapse: collapse; width: 100%; min-width: 820px; font-size: 14px; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #21262d; white-space: nowrap; }}
  th {{ color: #8b949e; font-weight: 600; cursor: pointer; user-select: none; position: sticky; top: 0; background: #0d1117; }}
  th:hover {{ color: #e6edf3; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.name {{ font-weight: 500; }}
  .pos {{ color: #f85149; }}   /* above avg = pricey (red) */
  .neg {{ color: #3fb950; }}   /* below avg = cheap (green) */
  .pos2 {{ color: #3fb950; }}  /* positive margin = good */
  .neg2 {{ color: #8b949e; }}
  .flag {{ display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 11px;
          font-weight: 700; color: #fff; margin-right: 4px; }}
  tr:hover td {{ background: #161b22; }}
</style>
</head>
<body>
<header>
  <h1>CS2 Skin Screener</h1>
  <div class="meta">Updated {generated} UTC · {rowcount} items · {alertcount} with active signals</div>
  <div class="legend">Buy = CSFloat (your buy market) · vs Avg = price vs its history on CSFloat ·
    Net Margin = buy CSFloat → sell Skinport after ~12% fee · 24h Vol = Steam units sold (liquidity).
    Click a header to sort.</div>
</header>
<div class="wrap">
<table id="board">
<thead><tr>
  <th data-col="0">Item</th>
  <th data-col="1" class="num">Buy (CSFloat)</th>
  <th data-col="2" class="num">Skinport</th>
  <th data-col="3" class="num">Steam</th>
  <th data-col="4" class="num">vs Avg</th>
  <th data-col="5" class="num">Net Margin</th>
  <th data-col="6" class="num">24h Vol</th>
  <th data-col="7" class="num">Pts</th>
  <th data-col="8">Signals</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<script>
document.querySelectorAll('th').forEach(function(th) {{
  th.addEventListener('click', function() {{
    var col = +th.dataset.col;
    var tb = document.querySelector('#board tbody');
    var rows = Array.from(tb.rows);
    var asc = th._asc = !th._asc;
    rows.sort(function(a, b) {{
      var x = a.cells[col].innerText.replace(/[$,%x+]/g, '').trim();
      var y = b.cells[col].innerText.replace(/[$,%x+]/g, '').trim();
      var nx = parseFloat(x), ny = parseFloat(y);
      if (!isNaN(nx) && !isNaN(ny)) return asc ? nx - ny : ny - nx;
      return asc ? x.localeCompare(y) : y.localeCompare(x);
    }});
    rows.forEach(function(r) {{ tb.appendChild(r); }});
  }});
}});
</script>
</body>
</html>
"""
