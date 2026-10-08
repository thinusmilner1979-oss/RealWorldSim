"""Live data sync: pull today's world from free public sources into a local cache.

    rws sync                      # all sources
    rws sync --sources worldbank  # one source
    (or the Sync button in the dashboard's Data tab)

Sources - all free, no API key, no account, each request made from the user's own machine:

  worldbank  GDP, population, growth, inflation, unemployment, government debt, military
             spending, armed-forces personnel - every country, most recent year.
  owid       Our World in Data: oil & gas production/consumption, SIPRI military spending,
             UN population, V-Dem democracy index (-> regime), food import share.
  ucdp       Uppsala Conflict Data Program: battle deaths last 12 months -> conflict intensity.
  gdelt      GDELT 2.0 event stream (last ~2 hours of world news): protest/conflict counts
             -> unrest index and pairwise tension bumps.
  climate    Open-Meteo ERA5 rainfall/temperature history -> per-country drought index;
             NOAA ONI -> El Nino / La Nina state.
  unhcr      UNHCR refugee stocks by origin and asylum country.
  portwatch  IMF PortWatch daily chokepoint transits -> observed shipping disruption.
  stooq      Daily gold, Brent, copper, wheat, gas quotes.
  fred       FRED CSV: Brent, Henry Hub, wheat, copper (overlaps stooq; either may be down).

Each fetcher returns a plain dict and never raises on network failure - it reports and
returns {} so the rest of the sync proceeds. Results merge into <cache>/live_seed.json
which World() picks up automatically.
"""
from __future__ import annotations

import inspect
import json
import time
from datetime import date, datetime
from pathlib import Path

from . import climate, fred, gdelt, owid, portwatch, stooq, ucdp, unhcr, worldbank

SOURCES = {
    "worldbank": worldbank.fetch, "owid": owid.fetch, "ucdp": ucdp.fetch, "gdelt": gdelt.fetch,
    "climate": climate.fetch, "unhcr": unhcr.fetch, "portwatch": portwatch.fetch, "stooq": stooq.fetch,
    "fred": fred.fetch,
}
DESCRIPTIONS = {
    "worldbank": "World Bank: GDP, population, growth, inflation, unemployment, debt, military",
    "owid": "Our World in Data: energy, SIPRI military, UN population, V-Dem democracy",
    "ucdp": "UCDP: battle deaths -> conflict intensity",
    "gdelt": "GDELT: world news events -> unrest, tension",
    "climate": "Open-Meteo ERA5 + NOAA ENSO: drought index per country (slow: ~196 calls)",
    "unhcr": "UNHCR: refugee stocks",
    "portwatch": "IMF PortWatch: chokepoint shipping disruption",
    "stooq": "Stooq: gold, Brent, copper, wheat, gas quotes",
    "fred": "FRED: Brent, Henry Hub, wheat, copper",
}
MERGE_KEYS = ("_prices", "_tension", "_conflicts", "_enso", "_chokepoints")


def cache_status(cache: Path) -> dict:
    f = Path(cache) / "live_seed.json"
    if not f.exists():
        return {"exists": False}
    try:
        d = json.loads(f.read_text())
    except json.JSONDecodeError:
        return {"exists": False}
    age_days = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 86400
    return {"exists": True, "date": d.get("_date"), "age_days": round(age_days, 1), "sources": d.get("_sources", {}),
            "countries": sum(1 for k in d if not k.startswith("_")), "path": str(f)}


def sync_all(cache: Path, sources: list[str] | None = None, verbose: bool = False, progress=None) -> Path:
    """Run the chosen fetchers; `progress(source, status, detail)` is called as each one starts/ends."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    chosen = sources or list(SOURCES)
    merged: dict = {"_date": date.today().isoformat(), "_sources": {}}
    # keep earlier results for sources not run this time
    prev = cache / "live_seed.json"
    if prev.exists() and sources:
        try:
            old = json.loads(prev.read_text())
            merged = old
            merged["_date"] = date.today().isoformat()
        except json.JSONDecodeError:
            pass
    for name in chosen:
        if name not in SOURCES:
            print(f"unknown source {name!r}; choose from {', '.join(SOURCES)}")
            continue
        if verbose:
            print(f"[{name}] fetching ...", flush=True)
        if progress:
            progress(name, "running", DESCRIPTIONS[name])
        t0 = time.time()
        try:
            fn = SOURCES[name]
            kwargs = {"verbose": verbose}
            if progress and "progress" in inspect.signature(fn).parameters:
                kwargs["progress"] = lambda done, total, _n=name: progress(_n, "running", f"{done}/{total}")
            data = fn(cache, **kwargs)
            err = None
        except Exception as e:  # noqa: BLE001 - a flaky source must not kill the sync
            print(f"[{name}] FAILED: {e}")
            data, err = {}, str(e)
        n = len(data.get("countries", {})) if data else 0
        merged["_sources"][name] = {"ok": bool(data), "countries": n, "seconds": round(time.time() - t0, 1),
                                    "error": err, "when": datetime.now().isoformat(timespec="seconds")}
        if progress:
            detail = err or (f"{n} countries" if n else ("ok" if data else "no data (offline? see terminal)"))
            progress(name, "ok" if data else "failed", detail)
        if not data:
            continue
        for iso, vals in data.get("countries", {}).items():
            merged.setdefault(iso, {}).update(vals)
        for key in MERGE_KEYS:
            if isinstance(data.get(key), dict):
                merged.setdefault(key, {}).update(data[key])
        (cache / f"{name}.json").write_text(json.dumps(data, indent=1))
    out = cache / "live_seed.json"
    out.write_text(json.dumps(merged, indent=1))
    if verbose:
        n = sum(1 for k in merged if not k.startswith("_"))
        print(f"merged live data for {n} countries -> {out}")
    return out
