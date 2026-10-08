"""Spot prices without a key: Stooq CSV quotes, with the World Bank monthly commodity
"Pink Sheet" (gold, urea, oil, wheat, copper) as the fallback when Stooq refuses.

https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv
https://www.worldbank.org/en/research/commodity-markets  (CMO-Historical-Data-Monthly.xlsx)
"""
from __future__ import annotations

from pathlib import Path

from .http import get_json, get_text

GOLDPRICE = "https://data-asg.goldprice.org/dbXRates/USD"  # keyless JSON, sometimes blocks scripts
PINK_SHEET = ("https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/"
              "CMO-Historical-Data-Monthly.xlsx")
URL_HIST = "https://stooq.com/q/d/l/?s={sym}&i=d"  # alternative endpoint: full daily history CSV
# Pink Sheet column header (as in the sheet) -> (our key, scale)
PINK_COLS = {"Gold": ("gold", 1.0), "Crude oil, Brent": ("oil", 1.0), "Copper": ("copper", 1 / 2204.6),
             "Wheat, US HRW": ("wheat", 1 / 36.74), "Urea": ("fertilizer", 1.0),
             "Natural gas, US": ("gas", 1.0), "Natural gas, Europe": ("gas_eu", 1.0)}

URL = "https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv"
SERIES = {
    "gold": ("xauusd", 1.0),      # USD/oz
    "oil": ("cb.f", 1.0),         # Brent front month USD/bbl
    "copper": ("hg.f", 1.0),      # USD/lb
    "wheat": ("zw.f", 1 / 100.0), # cents/bu -> USD/bu
    "gas": ("ng.f", 1.0),         # Henry Hub USD/MMBtu
}


def parse(csv_text: str) -> float | None:
    """Last Close in a Stooq CSV (works for both the quote and the history endpoint)."""
    lines = [ln for ln in csv_text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    header = lines[0].split(",")
    try:
        col = header.index("Close")
    except ValueError:
        return None
    for row in reversed(lines[1:]):
        parts = row.split(",")
        try:
            return float(parts[col])
        except (ValueError, IndexError):
            continue
    return None


def parse_pink_sheet(xlsx_bytes: bytes) -> dict[str, float]:
    """Latest monthly values from the World Bank CMO workbook (sheet 'Monthly Prices')."""
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
    out: dict[str, float] = {}
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


def fetch(cache: Path, verbose: bool = False) -> dict:
    prices = {}
    for key, (sym, scale) in SERIES.items():
        v = None
        for url in (URL.format(sym=sym), URL_HIST.format(sym=sym)):
            try:
                v = parse(get_text(url, timeout=30, browser=True))
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  stooq {sym}: {e}")
                continue
            if v:
                break
        if v:
            prices[key] = round(v * scale, 3)
            if verbose:
                print(f"  {key:<7} {prices[key]}")
    if len(prices) < len(SERIES):
        try:
            from .http import get

            pink = parse_pink_sheet(get(PINK_SHEET, timeout=180, browser=True))
            month = pink.pop("_month", "?")
            for k, v in pink.items():
                prices.setdefault(k, v)
            if verbose and pink:
                print(f"  world bank pink sheet ({month}):", ", ".join(f"{k} {v}" for k, v in pink.items()))
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  world bank pink sheet: {e}")
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
