"""Spot prices without a key.

Oil, gas, wheat and copper come daily from FRED (sync/fred.py). This module covers what
FRED does not: spot gold from gold-api.com (free JSON, no key). Yahoo Finance and Stooq
were tried and dropped - Yahoo rate-limits scripts outright (429 even on the cookie
handshake) and Stooq's quote endpoints now answer 404. The World Bank "Pink Sheet"
workbook is parsed only on request (`pink_sheet()`), because the public link is a dated
snapshot and a stale price is worse than none.
"""
from __future__ import annotations

from pathlib import Path

from .http import get, get_json

GOLD_API = "https://api.gold-api.com/price/XAU"
PINK_SHEET = ("https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/"
              "CMO-Historical-Data-Monthly.xlsx")
PINK_COLS = {"Gold": ("gold", 1.0), "Crude oil, Brent": ("oil", 1.0), "Copper": ("copper", 1 / 2204.6),
             "Wheat, US HRW": ("wheat", 1 / 36.74), "Urea": ("fertilizer", 1.0),
             "Natural gas, US": ("gas", 1.0), "Natural gas, Europe": ("gas_eu", 1.0)}


def parse_gold_api(payload: dict) -> float | None:
    try:
        return float(payload["price"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_pink_sheet(xlsx_bytes: bytes) -> dict[str, float | str]:
    """Latest monthly values (+ '_month') from the World Bank CMO workbook, sheet 'Monthly Prices'."""
    import io

    try:
        import openpyxl
    except ImportError:
        return {}
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb["Monthly Prices"] if "Monthly Prices" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    header_i = next((i for i, r in enumerate(rows) if r and any(isinstance(c, str) and "Gold" in c for c in r)), None)
    if header_i is None:
        return {}
    header = [str(c).strip() if c is not None else "" for c in rows[header_i]]
    cols = {name: header.index(name) for name in PINK_COLS if name in header}
    out: dict[str, float | str] = {}
    for r in reversed(rows[header_i + 1:]):
        if not r or r[0] is None:
            continue
        for name, idx in cols.items():
            key, scale = PINK_COLS[name]
            v = r[idx] if idx < len(r) else None
            if key not in out and isinstance(v, (int, float)):
                out[key] = round(float(v) * scale, 3)
                out.setdefault("_month", str(r[0]))
        if len(out) >= len(cols) + 1:
            break
    return out


def pink_sheet() -> dict[str, float | str]:
    return parse_pink_sheet(get(PINK_SHEET, timeout=180, browser=True))


def fetch(cache: Path, verbose: bool = False) -> dict:
    try:
        v = parse_gold_api(get_json(GOLD_API, timeout=20, browser=True))
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  gold-api.com: {e}")
        return {}
    if not v:
        return {}
    if verbose:
        print(f"  gold    {v:.2f} USD/oz (gold-api.com)")
    return {"_prices": {"gold": round(v, 2)}}
