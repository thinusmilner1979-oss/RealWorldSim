"""Run an ensemble of simulations from a historical scenario and collect what we score."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from multiprocessing import Pool

import numpy as np

from ..engine.params import Params
from ..engine.simulation import Simulation

SCORED_EVENT_TYPES = {"war_start", "war_escalation", "civil_war", "coup", "debt_crisis", "government_falls",
                      "pandemic", "chokepoint_closed", "financial_crisis", "ceasefire"}
COUNTRY_FIELDS = ("growth", "inflation")


def yearly_mean(dates: list[str], values: list[float]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for d, v in zip(dates, values, strict=True):
        acc[d[:4]].append(v)
    return {y: float(np.mean(v)) for y, v in acc.items()}


def run_one(args: tuple) -> dict:
    seed, scenario, start_iso, end_iso, params_dict, countries = args
    start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    params = Params.from_dict(params_dict) if params_dict else None
    sim = Simulation(seed=seed, start=start, params=params, scenario=scenario, use_live=False)
    days = (end - start).days
    events: list[dict] = []
    step = 365
    while sim.day < days:
        events.extend(sim.step(min(step, days - sim.day)))
    h = sim.global_history()
    out = {
        "seed": seed,
        "series": {k: yearly_mean(h["dates"], h[k]) for k in ("world_growth", "world_inflation", "oil", "gold",
                                                              "wheat", "active_wars")},
        "country_series": {},
        "events": [{"type": e["type"], "country": e.get("country"), "country2": e.get("country2"),
                    "date": e["date"]} for e in events if e["type"] in SCORED_EVENT_TYPES],
        "final": {"world_gdp": sim.world.world_gdp(), "oil": sim.world.prices["oil"],
                  "active_wars": len(sim.world.active_conflicts())},
    }
    ch_dates = sim.history.monthly_dates
    for iso in countries:
        if iso in sim.world.index:
            ch = sim.country_history(iso)
            out["country_series"][iso] = {f: yearly_mean(ch_dates, ch[f]) for f in COUNTRY_FIELDS}
    return out


def run_ensemble(scenario: dict, start: str, end: str, runs: int = 20, workers: int | None = None,
                 params: Params | None = None, countries: tuple[str, ...] = ("USA", "CHN", "DEU", "ZAF", "RUS",
                                                                               "TUR", "ARG"),
                 progress=None) -> list[dict]:
    jobs = [(seed, scenario, start, end, params.to_dict() if params else None, countries) for seed in range(runs)]
    results: list[dict] = []
    if workers == 1 or runs == 1:
        for j in jobs:
            results.append(run_one(j))
            if progress:
                progress(len(results), runs)
        return results
    with Pool(processes=workers) as pool:
        for r in pool.imap_unordered(run_one, jobs):
            results.append(r)
            if progress:
                progress(len(results), runs)
    results.sort(key=lambda r: r["seed"])
    return results
