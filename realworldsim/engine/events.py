"""Exogenous shocks and the headline generator.

Random events the model cannot derive from its own state: natural disasters,
pandemics, financial panics, technology booms, droughts, cyber-attacks, terror.
Each applies a direct hit to the state and logs a headline for the ticker.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from .params import EventParams
from .world import World

DT = 1.0 / 365.0

# Relative natural-disaster exposure by UN sub-region (earthquakes, cyclones, floods).
DISASTER_EXPOSURE = {
    "South-Eastern Asia": 2.0, "Southern Asia": 1.8, "Eastern Asia": 1.5, "Caribbean": 1.8,
    "Central America": 1.6, "Melanesia": 1.5, "Micronesia": 1.5, "Polynesia": 1.5,
    "Western Asia": 1.0, "Sub-Saharan Africa": 1.1, "Eastern Africa": 1.3, "Western Africa": 1.0,
    "Middle Africa": 0.9, "Southern Africa": 0.8, "Northern Africa": 0.7, "South America": 1.1,
    "Northern America": 1.0, "Western Europe": 0.5, "Northern Europe": 0.4, "Southern Europe": 0.8,
    "Eastern Europe": 0.5, "Central Asia": 0.8, "Australia and New Zealand": 1.0,
}


class EventState:
    def __init__(self, world: World):
        self.exposure = np.array([DISASTER_EXPOSURE.get(sr, 1.0) for sr in world.subregion])
        self.exposure *= world.s["population"] ** 0.3 / (world.s["population"] ** 0.3).mean()
        self.pandemic_days = 0
        self.financial_crisis_days = 0
        self.tech_boom_days = 0


def _p(annual: float) -> float:
    return 1.0 - float(np.exp(-annual * DT))


def step_events(world: World, p: EventParams, es: EventState, rng: np.random.Generator,
                events: list[dict], today: date, market_state) -> None:
    s = world.s
    n = world.n

    # ---- natural disasters ----------------------------------------------------
    haz = p.disaster_hazard * es.exposure / es.exposure.sum()
    hits = rng.random(n) < (1 - np.exp(-haz * DT))
    for i in np.where(hits)[0]:
        sev = float(np.clip(rng.lognormal(-1.2, 0.8), 0.05, 1.0))
        code = world.iso[i]
        world.exo_growth[i] -= 6.0 * sev * (1.5 - s["stability"][i])
        s["inflation"][i] += 1.5 * sev
        s["unrest"][i] += 0.1 * sev
        s["deficit"][i] += 1.0 * sev
        kind = rng.choice(["earthquake", "cyclone", "floods", "wildfires", "drought"])
        events.append({"type": "disaster", "country": code, "severity": 0.3 + 0.6 * sev,
                       "text": f"Major {kind} strikes {world.names[code]}"
                               + (" — thousands feared dead" if sev > 0.5 else "")})

    # ---- drought in breadbaskets -----------------------------------------------
    if rng.random() < _p(p.drought_hazard):
        sev = float(np.clip(rng.normal(0.5, 0.2), 0.1, 1.0))
        market_state.drought = min(1.0, market_state.drought + sev)
        events.append({"type": "drought", "country": None, "severity": 0.5,
                       "text": "Severe drought hits major grain-exporting regions; harvest forecasts cut"})

    # ---- pandemic -------------------------------------------------------------
    if es.pandemic_days == 0 and rng.random() < _p(p.pandemic_hazard):
        es.pandemic_days = 1
        events.append({"type": "pandemic", "country": None, "severity": 1.0,
                       "text": "WHO declares pandemic as novel virus spreads across continents"})
    if es.pandemic_days > 0:
        es.pandemic_days += 1
        phase = es.pandemic_days / 365.0
        hit = 6.0 * np.exp(-((phase - 0.4) ** 2) / 0.08)  # growth gap peaking ~5 months in (pp)
        world.exo_growth -= hit * 4 * DT       # steady state of the decaying gap ~= hit
        s["deficit"] += 0.4 * hit * DT * 4
        s["unemployment"] += 0.2 * hit * DT * 4
        if es.pandemic_days > 365 * 2:
            es.pandemic_days = 0
            events.append({"type": "pandemic_end", "country": None, "severity": 0.4,
                           "text": "Pandemic declared over as cases fall worldwide"})

    # ---- financial crisis: more likely when debt and rates are high -------------------
    w = world.gdp_weights()
    debt = float((s["debt_gdp"] * w).sum())
    rate = float((s["policy_rate"] * w).sum())
    risk_mult = max(0.2, (debt - 70) / 40) * max(0.3, rate / 4)
    if es.financial_crisis_days == 0 and rng.random() < _p(p.financial_crisis_hazard * risk_mult):
        es.financial_crisis_days = 1
        world.exo_growth -= 3.0 * (0.5 + np.clip(s["debt_gdp"], 0, 200) / 200)
        s["unemployment"] += 0.5
        s["risk"] += 0.2
        world.prices["gold"] *= 1.08
        world.prices["oil"] *= 0.8
        world.prices["copper"] *= 0.85
        events.append({"type": "financial_crisis", "country": None, "severity": 1.0,
                       "text": "Global financial crisis: markets crash, credit freezes, central banks intervene"})
    if es.financial_crisis_days > 0:
        es.financial_crisis_days += 1
        world.exo_growth -= 1.5 * 4 * DT * (1 - es.financial_crisis_days / 365)  # lingering credit crunch
        if es.financial_crisis_days > 365:
            es.financial_crisis_days = 0

    # ---- technology boom -------------------------------------------------------
    if es.tech_boom_days == 0 and rng.random() < _p(p.tech_boom_hazard):
        es.tech_boom_days = 1
        events.append({"type": "tech_boom", "country": None, "severity": 0.5,
                       "text": "Productivity surge: new technology wave lifts growth forecasts in advanced economies"})
    if es.tech_boom_days > 0:
        es.tech_boom_days += 1
        adv = np.array([g == "high_oecd" for g in world.income_group])
        s["growth_trend"][adv] += 0.4 * DT
        if es.tech_boom_days > 365 * 4:
            es.tech_boom_days = 0

    # ---- cyber-attacks between rivals -----------------------------------------
    if rng.random() < _p(p.cyberattack_hazard):
        pairs = np.argwhere(world.tension > 0.5)
        if len(pairs):
            i, j = pairs[rng.integers(len(pairs))]
            world.tension[i, j] = world.tension[j, i] = min(1.0, world.tension[i, j] + 0.04)
            world.exo_growth[j] -= 0.5
            events.append({"type": "cyberattack", "country": world.iso[i], "country2": world.iso[j], "severity": 0.5,
                           "text": f"Massive cyber-attack cripples infrastructure in {world.names[world.iso[j]]}; "
                                   f"{world.names[world.iso[i]]} blamed"})

    # ---- terror attacks: weighted to unstable states and their rivals --------------
    if rng.random() < _p(p.terror_hazard):
        weights = (1.2 - s["stability"]) ** 3 * (0.5 + s["war_intensity"] * 3 + s["unrest"])
        weights /= weights.sum()
        i = rng.choice(n, p=weights)
        s["unrest"][i] += 0.05
        s["stability"][i] -= 0.02
        events.append({"type": "terror", "country": world.iso[i], "severity": 0.6,
                       "text": f"Terror attack in {world.names[world.iso[i]]} kills dozens"})

    # ---- slow structural: potential growth converges by income ----------------
    conv = np.array([1.5 if g == "high_oecd" else 2.5 if g == "high" else 3.2 if g == "upper_middle"
                     else 4.3 if g == "lower_middle" else 4.5 for g in world.income_group])
    s["growth_trend"] += (conv - s["growth_trend"]) * 0.05 * DT
    s["growth_trend"] -= 0.5 * s["war_intensity"] * DT  # wars destroy capital


def market_headlines(world: World, prev: dict[str, float], events: list[dict], today: date) -> None:
    """Emit ticker items for notable daily/weekly price moves."""
    for k, label, unit in (("oil", "Brent crude", "$/bbl"), ("gas_eu", "European gas", "€/MWh"),
                           ("wheat", "Wheat", "$/bu"), ("gold", "Gold", "$/oz")):
        if k not in prev:
            continue
        ret = world.prices[k] / prev[k] - 1
        if abs(ret) > 0.06:
            direction = "surges" if ret > 0 else "plunges"
            events.append({"type": "market", "country": None, "severity": 0.4 + min(abs(ret), 0.5),
                           "text": f"{label} {direction} {abs(ret) * 100:.0f}% to {world.prices[k]:,.1f} {unit}"})
