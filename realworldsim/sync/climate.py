"""Weather and climate (free, no key):

* Open-Meteo archive API (ERA5 reanalysis): daily rain and temperature at each country's
  label point for the last N years -> a drought index: the last 90 days' rainfall vs. the
  same window's average in earlier years, and the temperature anomaly.
  https://open-meteo.com/en/docs/historical-weather-api  (non-commercial use, ~10k calls/day)
* NOAA Climate Prediction Center ONI table -> current El Nino / La Nina state.
  https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

The weather itself comes from the agencies' models; what we add is the consequence chain
(drought -> harvests -> food prices -> unrest). Seasonal forecasts and CMIP6 projections
are on the roadmap - same API family.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

from ..engine.world import DATA_DIR
from .http import get_json, get_text

ARCHIVE = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           "&start_date={start}&end_date={end}&daily=precipitation_sum,temperature_2m_mean&timezone=UTC")
ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
YEARS_BACK = 6
WINDOW = 90


def drought_index(dates: list[str], rain: list[float | None], temp: list[float | None]) -> dict:
    """Rain over the last 90 days vs. the mean of the same calendar window in previous years.

    Returns a drought index in [-1, 1] (positive = drier than normal; +1 ~ no rain at all)
    and a temperature anomaly in degC for the same window.
    """
    if len(dates) < WINDOW * 2:
        return {}
    last = date.fromisoformat(dates[-1])
    first = last - timedelta(days=WINDOW - 1)
    by_date = {date.fromisoformat(d): (r, t) for d, r, t in zip(dates, rain, temp, strict=True)}

    def window_sum(end: date) -> tuple[float, float, int]:
        rs, ts, n = 0.0, 0.0, 0
        for k in range(WINDOW):
            v = by_date.get(end - timedelta(days=k))
            if v and v[0] is not None:
                rs += v[0]
                ts += v[1] if v[1] is not None else 0.0
                n += 1
        return rs, ts, n

    r_now, t_now, n_now = window_sum(last)
    if n_now < WINDOW * 0.8:
        return {}
    past_r, past_t = [], []
    for y in range(1, YEARS_BACK + 1):
        try:
            end = last.replace(year=last.year - y)
        except ValueError:  # 29 Feb
            end = last.replace(year=last.year - y, day=28)
        if end - timedelta(days=WINDOW) < date.fromisoformat(dates[0]):
            break
        rs, ts, n = window_sum(end)
        if n >= WINDOW * 0.8:
            past_r.append(rs)
            past_t.append(ts / n)
    if not past_r:
        return {}
    norm = sum(past_r) / len(past_r)
    if norm < 5.0:  # deserts: rain anomaly is meaningless, use temperature only
        idx = 0.0
    else:
        idx = max(-1.0, min(1.0, (norm - r_now) / norm))
    t_anom = (t_now / n_now) - sum(past_t) / len(past_t)
    return {"drought_index": round(idx, 3), "rain_90d_mm": round(r_now, 1), "rain_90d_normal_mm": round(norm, 1),
            "temp_anomaly_c": round(t_anom, 2), "window_end": last.isoformat(), "first": first.isoformat()}


def parse_oni(text: str) -> dict:
    """Latest ONI value: > 0.5 El Nino, < -0.5 La Nina."""
    rows = [ln.split() for ln in text.strip().splitlines()[1:] if ln.strip()]
    if not rows:
        return {}
    season, year, _total, anom = rows[-1][:4]
    v = float(anom)
    state = "el_nino" if v >= 0.5 else "la_nina" if v <= -0.5 else "neutral"
    return {"oni": v, "season": season, "year": int(year), "state": state}


def fetch(cache: Path, verbose: bool = False, progress=None) -> dict:
    countries_meta = json.loads((DATA_DIR / "countries.json").read_text())["countries"]
    end = date.today() - timedelta(days=6)  # ERA5 lags ~5 days
    start = date(end.year - YEARS_BACK, 1, 1)
    out: dict[str, dict] = {}
    n = len(countries_meta)
    for i, c in enumerate(countries_meta):
        url = ARCHIVE.format(lat=c["lat"], lon=c["lon"], start=start.isoformat(), end=end.isoformat())
        try:
            d = get_json(url, timeout=60)["daily"]
            res = drought_index(d["time"], d["precipitation_sum"], d["temperature_2m_mean"])
            if res:
                out[c["iso3"]] = res
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  open-meteo {c['iso3']}: {e}")
            time.sleep(1.0)
        if progress:
            progress(i + 1, n)
        time.sleep(0.08)  # stay well inside the free tier
    enso = {}
    try:
        enso = parse_oni(get_text(ONI))
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  noaa oni: {e}")
    if verbose:
        dry = sorted(out.items(), key=lambda kv: -kv[1]["drought_index"])[:6]
        print(f"  {len(out)} countries; driest vs normal:",
              ", ".join(f"{k} {v['drought_index']:+.2f}" for k, v in dry))
        if enso:
            print(f"  ENSO: {enso['state']} (ONI {enso['oni']:+.1f}, {enso['season']} {enso['year']})")
    return {"countries": out, "_enso": enso} if out or enso else {}
