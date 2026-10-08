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


# ENSO teleconnection sign by UN sub-region: +1 El Nino tends to dry it, -1 El Nino tends to wet it.
ENSO_SIGN = {"Southern Africa": 1, "Eastern Africa": -0.5, "Australia and New Zealand": 1, "South-Eastern Asia": 1,
             "Southern Asia": 0.7, "Melanesia": 1, "Central America": 0.8, "Caribbean": 0.5, "South America": -0.3,
             "Northern America": -0.4, "Eastern Asia": 0.2, "Western Africa": 0.3, "Middle Africa": 0.3}
BREADBASKETS = {"UKR": 0.10, "RUS": 0.20, "USA": 0.15, "CAN": 0.07, "AUS": 0.07, "FRA": 0.05, "ARG": 0.06,
                "IND": 0.08, "KAZ": 0.03, "BRA": 0.08, "CHN": 0.11}


class EventState:
    def __init__(self, world: World):
        self.exposure = np.array([DISASTER_EXPOSURE.get(sr, 1.0) for sr in world.subregion])
        self.exposure *= world.s["population"] ** 0.3 / (world.s["population"] ** 0.3).mean()
        self.enso_sign = np.array([ENSO_SIGN.get(sr, 0.0) for sr in world.subregion])
        self.subregions = sorted(set(world.subregion))
        self.subregion_idx = np.array(world.subregion)
        self.breadbasket_weights = np.zeros(world.n)
        for code, w in BREADBASKETS.items():
            if code in world.index:
                self.breadbasket_weights[world.index[code]] = w
        self.disaster_mult = 1.0
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
    haz = p.disaster_hazard * getattr(es, "disaster_mult", 1.0) * es.exposure / es.exposure.sum()
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

    # ---- climate: per-country drought index, ENSO, warming trend ------------------
    world.climate_years += DT
    warming = 1 + p.climate_trend * world.climate_years
    # ENSO random-walks between La Nina and El Nino on a ~3-4 year cycle
    world.enso += (-0.4 * world.enso) * DT + rng.normal(0, 0.9) * np.sqrt(DT)
    world.enso = float(np.clip(world.enso, -2.5, 2.5))
    world.enso_state = "el_nino" if world.enso >= 0.5 else "la_nina" if world.enso <= -0.5 else "neutral"
    # regional ENSO teleconnections (positive = El Nino dries it out)
    enso_push = p.enso_strength * world.enso * es.enso_sign * DT
    s["drought"] += -p.drought_decay * s["drought"] * DT + enso_push
    # regional drought / wet spells, more frequent as the world warms
    if rng.random() < _p(p.drought_hazard * warming):
        sr = rng.choice(es.subregions)
        mask = es.subregion_idx == sr
        sev = float(np.clip(rng.normal(0.5, 0.2), 0.1, 1.0))
        s["drought"][mask] = np.minimum(1.0, s["drought"][mask] + sev)
        events.append({"type": "drought", "country": world.iso[int(np.where(mask)[0][0])], "severity": 0.5,
                       "text": f"Severe drought across {sr}; harvest forecasts cut"})
    if rng.random() < _p(p.bumper_harvest_hazard):
        sr = rng.choice(es.subregions)
        mask = es.subregion_idx == sr
        s["drought"][mask] = np.maximum(-1.0, s["drought"][mask] - float(np.clip(rng.normal(0.4, 0.15), 0.1, 0.8)))
        events.append({"type": "harvest", "country": world.iso[int(np.where(mask)[0][0])], "severity": 0.2,
                       "text": f"Good rains bring record harvests in {sr}"})
    s["drought"] = np.clip(s["drought"], -1, 1)
    # breadbasket drought feeds the world grain market
    bb = es.breadbasket_weights
    market_state.drought = float(np.clip((s["drought"] * bb).sum(), -1, 1))
    es.disaster_mult = warming

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
