"""FRED (St. Louis Fed) - the CSV graph endpoint needs no API key."""
from __future__ import annotations

from pathlib import Path

from .http import get_text

SERIES = {
    "oil": ("DCOILBRENTEU", 1.0),        # Brent, USD/bbl, daily
    "gas": ("DHHNGSP", 1.0),             # Henry Hub, USD/MMBtu, daily
    "wheat": ("PWHEAMTUSDM", 1 / 36.74), # USD/metric ton monthly -> USD/bushel
    "copper": ("PCOPPUSDM", 1 / 2204.6), # USD/metric ton monthly -> USD/lb
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"


def latest_value(csv_text: str) -> float | None:
    for line in reversed(csv_text.strip().splitlines()):
        parts = line.split(",")
        if len(parts) == 2 and parts[1] not in (".", "", "VALUE"):
            try:
                return float(parts[1])
            except ValueError:
                continue
    return None


def fetch(cache: Path, verbose: bool = False) -> dict:
    prices = {}
    for key, (sid, scale) in SERIES.items():
        try:
            v = latest_value(get_text(URL.format(id=sid)))
        except Exception as e:  # noqa: BLE001
            print(f"  fred {sid}: {e}")
            continue
        if v is not None:
            prices[key] = round(v * scale, 3)
            if verbose:
                print(f"  {key:<7} {prices[key]}")
    return {"_prices": prices} if prices else {}
