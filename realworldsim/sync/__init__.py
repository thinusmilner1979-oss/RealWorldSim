"""Live data sync: pull today's world from free public sources into a local cache.

    rws sync                      # all sources
    rws sync --sources worldbank  # one source

Sources (all free, no API key, no account):

  worldbank  GDP, population, growth, inflation, unemployment, government debt,
             military spending - every country, most recent year available.
  ucdp       Uppsala Conflict Data Program georeferenced events: battle deaths in the
             last 12 months -> conflict intensity per country.
  gdelt      GDELT 2.0 event stream (last ~2 hours of global news events): protest and
             conflict event counts -> unrest index and pairwise tension bumps.
  fred       St. Louis Fed FRED CSV endpoint: latest Brent, Henry Hub, wheat, copper.

Each fetcher returns a plain dict and never raises on network failure - it reports
and returns {} so the rest of the sync can proceed. The merged result is written to
<cache>/live_seed.json which World() picks up automatically.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import fred, gdelt, ucdp, worldbank

SOURCES = {"worldbank": worldbank.fetch, "ucdp": ucdp.fetch, "gdelt": gdelt.fetch, "fred": fred.fetch}


def sync_all(cache: Path, sources: list[str] | None = None, verbose: bool = False) -> Path:
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    chosen = sources or list(SOURCES)
    merged: dict = {"_date": date.today().isoformat(), "_sources": {}}
    for name in chosen:
        if name not in SOURCES:
            print(f"unknown source {name!r}; choose from {', '.join(SOURCES)}")
            continue
        if verbose:
            print(f"[{name}] fetching ...", flush=True)
        try:
            data = SOURCES[name](cache, verbose=verbose)
        except Exception as e:  # noqa: BLE001 - a flaky source must not kill the sync
            print(f"[{name}] FAILED: {e}")
            data = {}
        merged["_sources"][name] = {"ok": bool(data), "fields": len(data.get("countries", {}))}
        if not data:
            continue
        for iso, vals in data.get("countries", {}).items():
            merged.setdefault(iso, {}).update(vals)
        for key in ("_prices", "_tension", "_conflicts"):
            if key in data:
                merged.setdefault(key, {}).update(data[key])
        (cache / f"{name}.json").write_text(json.dumps(data, indent=1))
    out = cache / "live_seed.json"
    out.write_text(json.dumps(merged, indent=1))
    if verbose:
        n = sum(1 for k in merged if not k.startswith("_"))
        print(f"merged live data for {n} countries -> {out}")
    return out
