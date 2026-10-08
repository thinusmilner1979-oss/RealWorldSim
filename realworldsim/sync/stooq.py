"""Stooq daily quotes as CSV (free, no key): gold, Brent, copper, wheat, a few FX rates.

https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv
"""
from __future__ import annotations

from pathlib import Path

from .http import get_json, get_text

GOLDPRICE = "https://data-asg.goldprice.org/dbXRates/USD"  # keyless JSON, used when Stooq refuses

URL = "https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv"
SERIES = {
    "gold": ("xauusd", 1.0),      # USD/oz
    "oil": ("cb.f", 1.0),         # Brent front month USD/bbl
    "copper": ("hg.f", 1.0),      # USD/lb
    "wheat": ("zw.f", 1 / 100.0), # cents/bu -> USD/bu
    "gas": ("ng.f", 1.0),         # Henry Hub USD/MMBtu
}


def parse(csv_text: str) -> float | None:
    lines = csv_text.strip().splitlines()
    if len(lines) < 2:
        return None
    header, row = lines[0].split(","), lines[1].split(",")
    try:
        return float(row[header.index("Close")])
    except (ValueError, IndexError):
        return None


def fetch(cache: Path, verbose: bool = False) -> dict:
    prices = {}
    for key, (sym, scale) in SERIES.items():
        try:
            text = get_text(URL.format(sym=sym), timeout=30, browser=True)
            v = parse(text)
            if v is None and verbose:
                print(f"  stooq {sym}: unexpected response: {text[:80]!r}")
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  stooq {sym}: {e}")
            continue
        if v:
            prices[key] = round(v * scale, 3)
            if verbose:
                print(f"  {key:<7} {prices[key]}")
    if "gold" not in prices:
        try:
            d = get_json(GOLDPRICE, timeout=30)
            v = float(d["items"][0]["xauPrice"])
            prices["gold"] = round(v, 2)
            if verbose:
                print(f"  gold    {v} (goldprice.org)")
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  goldprice.org: {e}")
    return {"_prices": prices} if prices else {}
