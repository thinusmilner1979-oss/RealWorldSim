"""The Simulation: owns a World, advances it one day at a time, records history,
accepts interventions, and produces snapshots for the UI.

    sim = Simulation(seed=42)
    sim.step(365)                      # one year
    sim.declare_war("CHN", "TWN", 0.6)
    sim.close_chokepoint("hormuz")
    snap = sim.snapshot()              # dict for the UI / JSON

Determinism: the same seed, start date and sequence of interventions always produce
the same world.
"""
from __future__ import annotations

import json
import pickle
from collections import deque
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .commodities import MarketState, step_commodities
from .economy import MacroState, step_macro
from .events import EventState, market_headlines, step_events
from .geopolitics import GeoState, step_geopolitics
from .params import Params
from .world import Conflict, World

HISTORY_FIELDS = ["gdp", "growth", "inflation", "unemployment", "policy_rate", "debt_gdp",
                  "fx", "stability", "unrest", "war_intensity", "mil_spend_gdp", "risk", "drought", "mil_power"]
PRICE_KEYS = ["oil", "gas", "gas_eu", "wheat", "copper", "gold", "fertilizer"]


class History:
    """Daily global series + monthly per-country snapshots (keeps memory small)."""

    def __init__(self, world: World):
        self.n = world.n
        self.daily_dates: list[str] = []
        self.daily: dict[str, list[float]] = {k: [] for k in PRICE_KEYS + ["world_growth", "world_inflation",
                                                                            "global_risk", "active_wars", "world_gdp"]}
        self.monthly_dates: list[str] = []
        self.monthly: dict[str, list[np.ndarray]] = {k: [] for k in HISTORY_FIELDS}

    def record_day(self, world: World, today: date) -> None:
        self.daily_dates.append(today.isoformat())
        w = world.gdp_weights()
        for k in PRICE_KEYS:
            self.daily[k].append(round(world.prices[k], 4))
        self.daily["world_growth"].append(round(float((world.s["growth"] * w).sum()), 4))
        self.daily["world_inflation"].append(round(float((world.s["inflation"] * w).sum()), 4))
        self.daily["global_risk"].append(round(world.global_risk(), 4))
        self.daily["active_wars"].append(len(world.active_conflicts()))
        self.daily["world_gdp"].append(round(world.world_gdp(), 1))

    def record_month(self, world: World, today: date) -> None:
        self.monthly_dates.append(today.isoformat())
        for k in HISTORY_FIELDS:
            self.monthly[k].append(world.s[k].astype(np.float32).copy())

    def country_series(self, i: int, field: str) -> list[float]:
        return [round(float(m[i]), 4) for m in self.monthly[field]]


class Simulation:
    def __init__(self, seed: int = 42, start: date | None = None, params: Params | None = None,
                 cache_dir: Path | None = None, scenario: dict | None = None, use_live: bool = True):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.params = params or Params()
        self.world = World(cache_dir=cache_dir, scenario=scenario, use_live=use_live)
        self.start = start or date.today()
        self.today = self.start
        self.day = 0
        self.macro = MacroState(self.world)
        self.market = MarketState(self.world, self.params.commodities)
        self.geo = GeoState(self.world)
        self.evs = EventState(self.world)
        self.history = History(self.world)
        self.events: deque[dict] = deque(maxlen=2000)
        self.interventions: list[dict] = []
        self._prev_prices_week = dict(self.world.prices)
        self.history.record_day(self.world, self.today)
        self.history.record_month(self.world, self.today)

    # ------------------------------------------------------------------ stepping
    def step(self, days: int = 1) -> list[dict]:
        new_events: list[dict] = []
        for _ in range(days):
            self.day += 1
            self.today = self.start + timedelta(days=self.day)
            todays: list[dict] = []
            step_geopolitics(self.world, self.params.geo, self.geo, self.rng, todays, self.today)
            step_commodities(self.world, self.params.commodities, self.market, self.rng, todays)
            step_macro(self.world, self.params.macro, self.macro, self.rng, todays, self.today)
            step_events(self.world, self.params.events, self.evs, self.rng, todays, self.today, self.market)
            if self.day % 7 == 0:
                market_headlines(self.world, self._prev_prices_week, todays, self.today)
                self._prev_prices_week = dict(self.world.prices)
            for e in todays:
                e["date"] = self.today.isoformat()
                e["day"] = self.day
            self.events.extend(todays)
            new_events.extend(todays)
            self.history.record_day(self.world, self.today)
            if self.today.day == 1:
                self.history.record_month(self.world, self.today)
        return new_events

    # ------------------------------------------------------------- interventions
    def _log(self, kind: str, **kw) -> None:
        rec = {"day": self.day, "date": self.today.isoformat(), "kind": kind, **kw}
        self.interventions.append(rec)
        self.events.append({"type": "intervention", "country": kw.get("a") or kw.get("country"),
                            "severity": 0.5, "date": self.today.isoformat(), "day": self.day,
                            "text": f"[USER] {kind} {json.dumps(kw)}"})

    def set_tension(self, a: str, b: str, value: float) -> None:
        i, j = self.world.i(a), self.world.i(b)
        v = float(np.clip(value, 0, 1))
        self.world.tension[i, j] = self.world.tension[j, i] = v
        self.world.tension_base[i, j] = self.world.tension_base[j, i] = max(self.world.tension_base[i, j], v * 0.7)
        self._log("set_tension", a=a, b=b, value=v)

    def declare_war(self, a: str, b: str, intensity: float = 0.5) -> Conflict:
        cid = f"user_{a.lower()}_{b.lower()}_{self.today.isoformat()}"
        kind = "civil" if a == b else "interstate"
        name = f"{self.world.names[a]} civil war" if a == b else f"{self.world.names[a]}–{self.world.names[b]} war"
        c = Conflict(id=cid, name=name, a=a, b=b, intensity=float(np.clip(intensity, 0.05, 1)),
                     started=self.today, type=kind, peak=intensity)
        self.world.conflicts.append(c)
        if a != b:
            i, j = self.world.i(a), self.world.i(b)
            self.world.tension[i, j] = self.world.tension[j, i] = 1.0
        self._log("declare_war", a=a, b=b, intensity=intensity)
        return c

    def end_conflict(self, conflict_id: str) -> bool:
        for c in self.world.conflicts:
            if c.id == conflict_id and c.ended is None:
                c.ended = self.today
                if c.a != c.b:
                    i, j = self.world.i(c.a), self.world.i(c.b)
                    self.world.tension[i, j] = self.world.tension[j, i] = min(self.world.tension[i, j], 0.55)
                self._log("ceasefire", conflict=conflict_id)
                return True
        return False

    def set_conflict_intensity(self, conflict_id: str, intensity: float) -> bool:
        for c in self.world.conflicts:
            if c.id == conflict_id and c.ended is None:
                c.intensity = float(np.clip(intensity, 0.02, 1))
                self._log("set_intensity", conflict=conflict_id, intensity=c.intensity)
                return True
        return False

    def sanction(self, a: str, b: str, strength: float = 1.0) -> None:
        self.world.sanctions[self.world.i(a), self.world.i(b)] = float(np.clip(strength, 0, 1))
        self.world.update_sanctioned_share()
        self._log("sanction", a=a, b=b, strength=strength)

    def alliance_sanction(self, alliance: str, target: str, strength: float = 1.0) -> None:
        for c in self.world.alliances.get(alliance, []):
            if c in self.world.index and c != target:
                self.world.sanctions[self.world.i(c), self.world.i(target)] = strength
        self.world.update_sanctioned_share()
        self._log("alliance_sanction", alliance=alliance, country=target, strength=strength)

    def close_chokepoint(self, key: str, closed: bool = True) -> None:
        cp = self.world.chokepoints[key]
        cp["closed"] = closed
        cp["closed_by"] = "user" if closed else None
        self._log("chokepoint", country=key, closed=closed)

    def oil_supply_shock(self, fraction: float) -> None:
        """Remove (positive) or add (negative) a fraction of world oil supply."""
        self.world.oil_supply_shock = float(np.clip(fraction, -0.5, 0.9))
        self._log("oil_supply_shock", fraction=fraction)

    def set_variable(self, country: str, field: str, value: float) -> None:
        if field not in self.world.s:
            raise KeyError(field)
        self.world.s[field][self.world.i(country)] = float(value)
        self._log("set_variable", country=country, field=field, value=value)

    def shock(self, country: str, kind: str, size: float = 1.0) -> None:
        """Named one-off shocks: 'recession', 'boom', 'hyperinflation', 'revolution', 'default'."""
        i = self.world.i(country)
        s = self.world.s
        if kind == "recession":
            s["growth"][i] -= 5 * size
        elif kind == "boom":
            s["growth"][i] += 4 * size
        elif kind == "hyperinflation":
            s["inflation"][i] += 50 * size
            s["fx"][i] *= 1 + 0.5 * size
        elif kind == "revolution":
            s["unrest"][i] = min(1.0, s["unrest"][i] + 0.5 * size)
            s["stability"][i] = max(0.05, s["stability"][i] - 0.3 * size)
        elif kind == "default":
            self.macro.debt_crisis[i] = True
            s["fx"][i] *= 1.3
        else:
            raise ValueError(kind)
        self._log("shock", country=country, kind=kind, size=size)

    # ---------------------------------------------------------------- snapshots
    def snapshot(self, fields: list[str] | None = None) -> dict[str, Any]:
        w = self.world
        fields = fields or ["gdp", "growth", "inflation", "unemployment", "policy_rate", "debt_gdp",
                            "stability", "unrest", "war_intensity", "fx", "risk", "mil_spend_gdp", "sanctioned_share",
                            "drought", "mil_power"]
        wgt = w.gdp_weights()
        return {
            "day": self.day,
            "date": self.today.isoformat(),
            "start": self.start.isoformat(),
            "seed": self.seed,
            "iso": w.iso,
            "fields": {k: np.round(w.s[k], 3).tolist() for k in fields},
            "prices": {k: round(v, 3) for k, v in w.prices.items()},
            "price_start": {k: round(v, 3) for k, v in w.price_start.items()},
            "world": {
                "gdp": round(w.world_gdp(), 1),
                "growth": round(float((w.s["growth"] * wgt).sum()), 3),
                "inflation": round(float((w.s["inflation"] * wgt).sum()), 3),
                "risk": round(w.global_risk(), 3),
                "active_wars": len(w.active_conflicts()),
                "refugees": round(float(w.s["refugees_out"].sum())),
                "oil_disruption": round(self.market.disruption["oil"], 3),
                "enso": round(w.enso, 2),
                "enso_state": w.enso_state,
            },
            "conflicts": [c.to_dict() for c in w.active_conflicts()],
            "chokepoints": {k: {"name": v["name"], "closed": v["closed"],
                                "observed": round(float(v.get("observed_disruption", 0.0)), 2)}
                            for k, v in w.chokepoints.items()},
            "hotspots": self.hotspots(12),
            "live_data_date": w.live_data_date,
        }

    def hotspots(self, k: int = 10) -> list[dict]:
        T = np.triu(self.world.tension, 1)
        idx = np.argpartition(T.ravel(), -k)[-k:]
        out = []
        for flat in idx[np.argsort(-T.ravel()[idx])]:
            i, j = divmod(int(flat), self.world.n)
            out.append({"a": self.world.iso[i], "b": self.world.iso[j], "tension": round(float(T[i, j]), 3)})
        return out

    def recent_events(self, limit: int = 100) -> list[dict]:
        return list(self.events)[-limit:]

    def global_history(self) -> dict[str, Any]:
        return {"dates": self.history.daily_dates, **self.history.daily}

    def country_history(self, code: str) -> dict[str, Any]:
        i = self.world.i(code)
        return {"dates": self.history.monthly_dates,
                **{k: self.history.country_series(i, k) for k in HISTORY_FIELDS}}

    # ------------------------------------------------------------- persistence
    def save(self, path: str | Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def load(path: str | Path) -> Simulation:
        with open(path, "rb") as f:
            return pickle.load(f)
