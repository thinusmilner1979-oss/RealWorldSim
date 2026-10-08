"""Historical starting states for backtests.

A backtest needs the world *as it was* on the start date. Two sources:

1. A bundled scenario file, `data/history/<year>.json`, hand-written from the public
   record (always available, approximate).
2. A synced history cache, `.rws_cache/history/worldbank_<year>.json`, produced by
   `rws sync --history <year>` - sourced World Bank values that override the bundled
   figures where present.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..engine.world import DATA_DIR
from ..sync import worldbank
from ..sync.http import get_json

HIST_DIR = DATA_DIR / "history"
WB_YEAR = "https://api.worldbank.org/v2/country/all/indicator/{ind}?format=json&date={year}&per_page=500"


def available_scenarios() -> list[int]:
    return sorted(int(p.stem) for p in HIST_DIR.glob("[0-9][0-9][0-9][0-9].json"))


def load_scenario(year: int, cache: Path | None = None) -> dict:
    """Bundled scenario for `year`, with synced World Bank history merged on top if cached."""
    path = HIST_DIR / f"{year}.json"
    if not path.exists():
        raise FileNotFoundError(f"no bundled scenario for {year}; available: {available_scenarios()}")
    scenario = json.loads(path.read_text())
    if cache is not None:
        synced = Path(cache) / "history" / f"worldbank_{year}.json"
        if synced.exists():
            hist = json.loads(synced.read_text())
            for iso, vals in hist.get("countries", {}).items():
                scenario["countries"].setdefault(iso, {}).update(
                    {k: v for k, v in vals.items() if not k.endswith("_year")})
            scenario["_synced"] = str(synced)
    return scenario


def load_scorecard(name: str = "scorecard_2015_2025") -> dict:
    return json.loads((HIST_DIR / f"{name}.json").read_text())


def fetch_history(year: int, cache: Path, verbose: bool = False) -> Path:
    """Pull World Bank values for one calendar year into the cache (free, no key)."""
    out_dir = Path(cache) / "history"
    out_dir.mkdir(parents=True, exist_ok=True)
    countries: dict[str, dict] = {}
    for ind, (field, conv) in worldbank.INDICATORS.items():
        try:
            payload = get_json(WB_YEAR.format(ind=ind, year=year))
        except Exception as e:  # noqa: BLE001
            print(f"  worldbank {ind} {year}: {e}")
            continue
        got = worldbank.parse(payload, field, conv)
        for iso, vals in got.items():
            countries.setdefault(iso, {}).update(vals)
        if verbose:
            print(f"  {ind:<20} {field:<14} {year}: {len(got)} countries")
    out = out_dir / f"worldbank_{year}.json"
    out.write_text(json.dumps({"year": year, "countries": countries}, indent=1))
    return out
