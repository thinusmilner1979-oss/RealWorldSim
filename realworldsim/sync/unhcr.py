"""UNHCR Refugee Population Statistics API (free, no key).

https://api.unhcr.org/population/v1/population/?year=<y>&coo_all=true&coa_all=true
Refugees + asylum seekers by country of origin and of asylum for the latest year.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .http import get_json

URL = "https://api.unhcr.org/population/v1/population/?limit=10000&page={page}&year={year}&coo_all=true&coa_all=true"


def aggregate(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:
        try:
            n = float(it.get("refugees", 0) or 0) + float(it.get("asylum_seekers", 0) or 0)
        except (TypeError, ValueError):
            continue
        coo, coa = it.get("coo_iso"), it.get("coa_iso")
        if coo and len(coo) == 3:
            out.setdefault(coo, {}).setdefault("refugees_out_live", 0.0)
            out[coo]["refugees_out_live"] += n
        if coa and len(coa) == 3:
            out.setdefault(coa, {}).setdefault("refugees_in_live", 0.0)
            out[coa]["refugees_in_live"] += n
    return out


def fetch(cache: Path, verbose: bool = False) -> dict:
    items: list[dict] = []
    for year in (date.today().year - 1, date.today().year - 2):
        page = 1
        items = []
        while page < 20:
            payload = get_json(URL.format(page=page, year=year), timeout=120)
            items.extend(payload.get("items", []))
            if page >= int(payload.get("maxPages", 1) or 1):
                break
            page += 1
        if items:
            break
    if not items:
        return {}
    countries = aggregate(items)
    if verbose:
        top = sorted(countries.items(), key=lambda kv: -kv[1].get("refugees_out_live", 0))[:6]
        print(f"  {len(items)} rows ({year});", ", ".join(f"{k} {int(v['refugees_out_live']/1e3)}k" for k, v in top))
    return {"countries": countries}
