"""World state: every country on earth as rows of numpy arrays.

The World object is deliberately dumb - it holds state and knows how to build
itself from the bundled seed data (plus a live-sync cache if present). All
dynamics live in economy.py, commodities.py, geopolitics.py and events.py.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Per-country scalar fields carried in the state. Order matters for snapshots.
COUNTRY_FIELDS = [
    "gdp",            # nominal GDP, USD bn
    "population",     # persons
    "growth",         # real GDP growth, annual %
    "growth_trend",   # potential growth, annual %
    "inflation",      # CPI inflation, annual %
    "inflation_target",
    "unemployment",   # %
    "unemployment_trend",
    "policy_rate",    # %
    "neutral_rate",   # %
    "debt_gdp",       # government debt, % GDP
    "deficit",        # fiscal deficit, % GDP (positive = deficit)
    "fx",             # currency index vs USD, 100 = start (higher = weaker)
    "stability",      # 0..1
    "regime",         # 0 democracy .. 1 autocracy
    "unrest",         # 0..1 civil unrest index
    "mil_spend_gdp",  # % GDP
    "oil_prod",       # mb/d
    "oil_cons",       # mb/d
    "gas_prod",       # bcm/yr
    "gas_cons",       # bcm/yr
    "food_import_share",  # share of food consumption imported (0..1)
    "war_intensity",  # 0..1 aggregate exposure to active wars
    "sanctioned_share",   # share of trade under sanction
    "refugees_out",   # cumulative, persons
    "refugees_in",
    "risk",           # composite risk premium 0..1
    "drought",        # -1..1 rainfall anomaly index (positive = drier than normal), decays toward climate trend
    "mil_power",      # military power index, USA = 1.0 (budget, personnel, technology, nuclear)
    "mil_personnel",  # armed forces personnel
]

INCOME_DEFAULTS = {
    # growth_trend, inflation, inflation_target, unemployment, policy_rate, neutral, debt_gdp, regime, stability
    "high_oecd":    (1.6, 2.5, 2.0, 5.5, 3.0, 2.5, 70, 0.12, 0.85),
    "high":         (2.5, 3.0, 2.5, 5.0, 4.0, 3.5, 50, 0.6, 0.75),
    "upper_middle": (3.2, 5.0, 3.5, 7.0, 7.0, 6.0, 55, 0.5, 0.6),
    "lower_middle": (4.5, 7.0, 4.5, 6.0, 8.5, 7.5, 55, 0.55, 0.5),
    "low":          (4.5, 9.0, 5.0, 6.0, 10.0, 9.0, 55, 0.7, 0.4),
    "unknown":      (3.0, 5.0, 3.5, 6.0, 6.0, 5.0, 55, 0.5, 0.6),
}


@dataclass
class Conflict:
    id: str
    name: str
    a: str
    b: str
    intensity: float
    started: date
    type: str = "interstate"  # interstate | civil | proxy
    supporters_a: list[str] = field(default_factory=list)
    supporters_b: list[str] = field(default_factory=list)
    spillover: list[str] = field(default_factory=list)
    days: int = 0
    ended: date | None = None
    peak: float = 0.0
    major: bool = False  # has crossed into major war (intensity >= 0.6) since it was last low
    outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "a": self.a, "b": self.b,
            "intensity": round(float(self.intensity), 3), "started": self.started.isoformat(),
            "type": self.type, "supporters_a": self.supporters_a, "supporters_b": self.supporters_b,
            "days": self.days, "ended": self.ended.isoformat() if self.ended else None,
            "peak": round(float(self.peak), 3), "outcome": self.outcome,
        }


class World:
    """Vectorised state of all countries plus pairwise matrices and markets."""

    def __init__(self, seed_dir: Path | None = None, cache_dir: Path | None = None,
                 scenario: dict | None = None, use_live: bool = True):
        """
        scenario: optional dict shaped like overrides.json that is merged on top of it -
                  used to start the world at a historical date (see backtest/).
                  Keys: countries (merge per country), rivalries (merge), unrest (merge),
                  commodities (merge), active_conflicts (replace), sanction_targets (replace),
                  alliances (replace).
        use_live: apply the `rws sync` cache if present (switched off for backtests).
        """
        seed_dir = seed_dir or DATA_DIR
        meta = json.loads((seed_dir / "countries.json").read_text())
        overrides = json.loads((seed_dir / "overrides.json").read_text())
        if scenario:
            overrides = merge_scenario(overrides, scenario)
        live = self._load_live_cache(cache_dir) if use_live else {}
        self.sanction_targets: dict[str, float] = overrides.get(
            "sanction_targets",
            {"RUS": 1.0, "IRN": 1.0, "PRK": 1.0, "BLR": 0.8, "VEN": 0.6, "SYR": 0.8, "MMR": 0.6, "CUB": 0.5})

        self.countries: list[dict] = meta["countries"]
        self.iso = [c["iso3"] for c in self.countries]
        self.index = {code: i for i, code in enumerate(self.iso)}
        self.names = {c["iso3"]: c["name"] for c in self.countries}
        self.n = len(self.iso)
        n = self.n

        # ---- scalar fields -------------------------------------------------
        self.s: dict[str, np.ndarray] = {f: np.zeros(n) for f in COUNTRY_FIELDS}
        self.nuclear = np.zeros(n, dtype=bool)
        self.income_group = [c["income_group"] for c in self.countries]
        self.lat = np.array([c["lat"] for c in self.countries])
        self.lon = np.array([c["lon"] for c in self.countries])
        self.region = [c["region"] for c in self.countries]
        self.subregion = [c["subregion"] for c in self.countries]

        ov = overrides["countries"]
        for i, c in enumerate(self.countries):
            g, infl, tgt, u, r, rn, debt, regime, stab = INCOME_DEFAULTS[c["income_group"]]
            # Natural Earth GDP is from 2019; scale forward ~24% nominal to 2025 as a crude default
            gdp = c["gdp_usd_bn"] * 1.24
            pop = c["population"] * 1.05
            o = dict(ov.get(c["iso3"], {}))
            o.update(live.get(c["iso3"], {}))
            vals = {
                "gdp": o.get("gdp_usd_bn", gdp),
                "population": o.get("population", pop),
                "growth": o.get("growth", g),
                "growth_trend": o.get("growth_trend", o.get("growth", g) * 0.6 + g * 0.4),
                "inflation": o.get("inflation", infl),
                "inflation_target": tgt,
                "unemployment": o.get("unemployment", u),
                "unemployment_trend": o.get("unemployment", u),
                "policy_rate": o.get("policy_rate",
                                     max(0.0, o.get("inflation", infl) + 1.0) if "inflation" in o else r),
                "neutral_rate": rn,
                "debt_gdp": o.get("debt_gdp", debt),
                "deficit": o.get("deficit", 3.0 if c["income_group"].startswith("high") else 4.0),
                "fx": 100.0,
                "stability": o.get("stability", stab),
                "regime": o.get("regime", regime),
                "unrest": max(overrides["unrest"].get(c["iso3"], 0.1), 0.6 * o.get("unrest_live", 0.0)),
                "mil_spend_gdp": o.get("mil_spend_gdp", 1.5),
                "oil_prod": o.get("oil_prod", 0.0),
                "oil_cons": o.get("oil_cons", 0.0),
                "gas_prod": o.get("gas_prod", 0.0),
                "gas_cons": o.get("gas_cons", 0.0),
                "food_import_share": o.get("food_import_share", 0.3),
                "war_intensity": 0.0,
                "sanctioned_share": 0.0,
                "refugees_out": 0.0,
                "refugees_in": 0.0,
                "risk": 0.0,
                "drought": float(o.get("drought_index", 0.0)),
                "mil_power": 0.0,
                "mil_personnel": o.get("mil_personnel", 0.0),
            }
            for k, v in vals.items():
                self.s[k][i] = float(v)
            self.nuclear[i] = bool(o.get("nuclear", False))

        # Refugee stocks from UNHCR when synced
        for i, c in enumerate(self.countries):
            lv = live.get(c["iso3"], {})
            self.s["refugees_out"][i] = float(lv.get("refugees_out_live", 0.0))
            self.s["refugees_in"][i] = float(lv.get("refugees_in_live", 0.0))
        # Military power index (USA = 1): budget, personnel, technology (GDP/head), nuclear
        self.update_military_power()

        # Fill in oil/gas consumption for countries without data: scale with GDP.
        no_oil = self.s["oil_cons"] == 0
        self.s["oil_cons"][no_oil] = self.s["gdp"][no_oil] * 0.00085  # ~0.85 kb/d per $bn
        no_gas = self.s["gas_cons"] == 0
        self.s["gas_cons"][no_gas] = self.s["gdp"][no_gas] * 0.02

        # Net oil import dependence as share of GDP (positive = importer)
        self._update_energy_balance(overrides["commodities"]["oil"]["price"])

        # ---- pairwise matrices --------------------------------------------
        self.distance = self._distance_matrix()
        self.alliances: dict[str, list[str]] = overrides["alliances"]
        self.alliance = self._alliance_matrix()
        self.trade = self._gravity_trade()
        self.tension_base = self._baseline_tension(overrides["rivalries"])
        for key, bump in live.get("_tension", {}).items():  # GDELT hostility bumps
            a, b = key.split("-")
            if a in self.index and b in self.index:
                i, j = self.index[a], self.index[b]
                self.tension_base[i, j] = self.tension_base[j, i] = min(1.0, self.tension_base[i, j] + float(bump))
        self.tension = self.tension_base.copy()
        self.sanctions = np.zeros((n, n))  # sanctions[i, j] = 1 if i sanctions j
        self._seed_sanctions()

        # ---- markets --------------------------------------------------------
        cm = overrides["commodities"]
        for k, v in live.get("_prices", {}).items():
            if k in cm and isinstance(v, (int, float)) and v > 0:
                cm[k]["price"] = float(v)
        self.prices: dict[str, float] = {
            "oil": cm["oil"]["price"], "gas": cm["gas"]["price"], "gas_eu": cm["gas"]["ttf_price"],
            "wheat": cm["wheat"]["price"], "copper": cm["copper"]["price"],
            "gold": cm["gold"]["price"], "fertilizer": cm["fertilizer"]["price"],
        }
        self.price_anchor = dict(self.prices)
        self.price_start = dict(self.prices)
        self.chokepoints: dict[str, dict] = {
            k: dict(v, closed=False) for k, v in overrides["chokepoints"].items() if not k.startswith("_")
        }
        self.oil_supply_shock = 0.0  # fraction of world supply removed by user intervention
        # climate: El Nino / La Nina state (ONI) and a slow warming trend applied in events.py
        enso = live.get("_enso", {}) if isinstance(live.get("_enso"), dict) else {}
        self.enso = float(enso.get("oni", 0.0))
        self.enso_state = enso.get("state", "neutral")
        self.climate_years = 0.0
        # chokepoint disruption observed in shipping data (PortWatch) - calibrated out at t=0
        for key, obs in (live.get("_chokepoints") or {}).items():
            if key in self.chokepoints:
                self.chokepoints[key]["observed_disruption"] = float(obs.get("disruption", 0.0))
        # exogenous growth gap (pp) set by events (pandemic, crises); decays in economy.py
        self.exo_growth = np.zeros(n)
        self.risk0 = None  # starting global risk, set by the simulation after construction

        # ---- conflicts ------------------------------------------------------
        self.conflicts: list[Conflict] = []
        for c in overrides["active_conflicts"]:
            if c["a"] in self.index and c["b"] in self.index:
                self.conflicts.append(
                    Conflict(
                        id=c["id"], name=c["name"], a=c["a"], b=c["b"], intensity=c["intensity"],
                        started=date.fromisoformat(c["started"]), type=c.get("type", "interstate"),
                        supporters_a=c.get("supporters_a", []), supporters_b=c.get("supporters_b", []),
                        spillover=c.get("spillover", []), peak=c["intensity"], major=c["intensity"] >= 0.6,
                    )
                )
        # live conflict intensities (UCDP battle deaths) adjust seeded conflicts and add missing ones
        covered = set()
        for c in self.conflicts:
            for code in (c.a, c.b):
                lv = live.get(code, {}).get("war_intensity_live")
                if lv is not None:
                    c.intensity = max(0.5 * c.intensity, float(lv)) if lv > 0 else c.intensity * 0.5
                    c.peak = max(c.peak, c.intensity)
                covered.add(code)
        for code, vals in live.items():
            if code.startswith("_") or code in covered or code not in self.index:
                continue
            lv = vals.get("war_intensity_live", 0.0)
            if lv >= 0.3:
                self.conflicts.append(Conflict(id=f"live_{code.lower()}", name=f"{self.names[code]} armed conflict",
                                               a=code, b=code, intensity=float(lv), started=date.today(), type="civil",
                                               peak=float(lv)))
        self.live_data_date: str | None = live.get("_date") if isinstance(live.get("_date"), str) else None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _load_live_cache(cache_dir: Path | None) -> dict:
        if cache_dir is None:
            cache_dir = Path.cwd() / ".rws_cache"
        f = Path(cache_dir) / "live_seed.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _distance_matrix(self) -> np.ndarray:
        lat = np.radians(self.lat)[:, None]
        lon = np.radians(self.lon)[:, None]
        dlat = lat - lat.T
        dlon = lon - lon.T
        a = np.sin(dlat / 2) ** 2 + np.cos(lat) * np.cos(lat.T) * np.sin(dlon / 2) ** 2
        return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

    def _alliance_matrix(self) -> np.ndarray:
        m = np.zeros((self.n, self.n))
        weights = {"NATO": 1.0, "EU": 0.8, "CSTO": 0.8, "US_PACIFIC": 0.8, "GCC": 0.6,
                   "AXIS_RESISTANCE": 0.6, "CHN_PARTNERS": 0.5, "BRICS": 0.2, "AU": 0.15,
                   "ASEAN": 0.3, "MERCOSUR": 0.3}
        for name, members in self.alliances.items():
            w = weights.get(name, 0.3)
            idx = [self.index[c] for c in members if c in self.index]
            for i in idx:
                for j in idx:
                    if i != j:
                        m[i, j] = max(m[i, j], w)
        return m

    def _gravity_trade(self) -> np.ndarray:
        """Row-normalised bilateral trade shares from a gravity model."""
        gdp = self.s["gdp"]
        d = self.distance + 500.0
        g = np.outer(gdp, gdp) / d ** 1.1
        np.fill_diagonal(g, 0.0)
        g *= (1.0 + 0.5 * self.alliance)  # allies trade more
        row = g.sum(axis=1, keepdims=True)
        row[row == 0] = 1.0
        return g / row

    def _baseline_tension(self, rivalries: dict) -> np.ndarray:
        t = np.full((self.n, self.n), 0.08)
        # neighbours have slightly more friction, allies less
        t += 0.07 * (self.distance < 1500)
        t -= 0.06 * self.alliance
        for key, v in rivalries.items():
            if key.startswith("_"):
                continue
            a, b = key.split("-")
            if a in self.index and b in self.index:
                i, j = self.index[a], self.index[b]
                t[i, j] = t[j, i] = v
        np.fill_diagonal(t, 0.0)
        return np.clip(t, 0.0, 1.0)

    def _seed_sanctions(self) -> None:
        west = [c for c in self.alliances["NATO"] + self.alliances["EU"] + ["AUS", "JPN", "KOR", "NZL", "CHE", "TWN"]]
        targets = self.sanction_targets
        for tgt, strength in targets.items():
            if tgt not in self.index:
                continue
            j = self.index[tgt]
            for c in set(west):
                if c in self.index and c != tgt:
                    self.sanctions[self.index[c], j] = strength
        if "USA" in self.index and "CHN" in self.index:
            self.sanctions[self.index["USA"], self.index["CHN"]] = 0.15
            self.sanctions[self.index["CHN"], self.index["USA"]] = 0.1
        self.update_sanctioned_share()

    def update_sanctioned_share(self) -> None:
        # share of j's trade that is with countries sanctioning it
        self.s["sanctioned_share"][:] = np.einsum("ij,ji->j", self.sanctions, self.trade)

    def _update_energy_balance(self, oil_price: float) -> None:
        """Net oil import bill as share of GDP (positive = importer, negative = exporter)."""
        net_mbd = self.s["oil_cons"] - self.s["oil_prod"]
        bill_bn = net_mbd * 1e6 * 365 * oil_price / 1e9
        self.oil_import_gdp = bill_bn / np.maximum(self.s["gdp"], 1.0)
        net_gas = self.s["gas_cons"] - self.s["gas_prod"]  # bcm/yr; 1 bcm ~ 35.3m MMBtu
        gas_price = self.prices.get("gas", 3.2) if hasattr(self, "prices") else 3.2
        gas_bill_bn = net_gas * 35.3 * gas_price / 1000.0
        self.gas_import_gdp = gas_bill_bn / np.maximum(self.s["gdp"], 1.0)

    def update_military_power(self) -> None:
        """0..~1.2 index: 0.5*log budget + 0.2*log personnel + 0.2*technology + 0.1*nuclear, USA = 1."""
        s = self.s
        budget = s["gdp"] * s["mil_spend_gdp"] / 100.0  # USD bn
        personnel = np.where(s["mil_personnel"] > 0, s["mil_personnel"], s["population"] * 0.004)
        s["mil_personnel"] = personnel
        tech = np.clip(np.log10(np.maximum(s["gdp"] / np.maximum(s["population"], 1) * 1e9, 300) / 300) / 2.3, 0, 1)
        raw = (0.5 * np.log10(budget + 0.5) / np.log10(1000) + 0.2 * np.log10(personnel / 1000 + 1) / 3.3
               + 0.2 * tech + 0.1 * self.nuclear)
        usa = self.index.get("USA")
        ref = raw[usa] if usa is not None else raw.max()
        s["mil_power"] = np.clip(raw / max(ref, 1e-6), 0.0, 1.5)

    # ---------------------------------------------------------------- queries
    def i(self, code: str) -> int:
        return self.index[code]

    def world_gdp(self) -> float:
        return float(self.s["gdp"].sum())

    def gdp_weights(self) -> np.ndarray:
        g = self.s["gdp"]
        return g / g.sum()

    def active_conflicts(self) -> list[Conflict]:
        return [c for c in self.conflicts if c.ended is None]

    def neighbours(self, i: int, km: float = 1200.0) -> np.ndarray:
        return np.where((self.distance[i] < km) & (np.arange(self.n) != i))[0]

    def global_risk(self) -> float:
        w = self.gdp_weights()
        war = float((self.s["war_intensity"] * w).sum())
        unrest = float((self.s["unrest"] * w).sum())
        tens = float(np.max(self.tension * (np.outer(w, w) ** 0.5))) * 10
        return float(np.clip(0.3 * war * 5 + 0.3 * unrest + 0.4 * min(tens, 1.0), 0, 1))

    def country_snapshot(self, code: str) -> dict[str, Any]:
        i = self.index[code]
        d = {k: float(v[i]) for k, v in self.s.items()}
        d["iso3"] = code
        d["name"] = self.names[code]
        d["nuclear"] = bool(self.nuclear[i])
        d["income_group"] = self.income_group[i]
        d["region"] = self.region[i]
        top = np.argsort(-self.tension[i])[:5]
        d["tensions"] = [{"with": self.iso[j], "value": round(float(self.tension[i, j]), 3)} for j in top]
        tp = np.argsort(-self.trade[i])[:5]
        d["trade_partners"] = [{"with": self.iso[j], "share": round(float(self.trade[i, j]), 3)} for j in tp]
        d["conflicts"] = [c.to_dict() for c in self.active_conflicts()
                          if code in (c.a, c.b) or code in c.supporters_a + c.supporters_b + c.spillover]
        d["sanctioned_by"] = [self.iso[j] for j in np.where(self.sanctions[:, i] > 0.3)[0]]
        return d


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 12742 * math.asin(math.sqrt(a))


def merge_scenario(base: dict, scenario: dict) -> dict:
    """Merge a scenario dict over the bundled overrides (see World.__init__)."""
    out = json.loads(json.dumps(base))  # deep copy
    for iso, vals in scenario.get("countries", {}).items():
        out["countries"].setdefault(iso, {}).update(vals)
    for key in ("rivalries", "unrest"):
        out[key].update(scenario.get(key, {}))
    for k, v in scenario.get("commodities", {}).items():
        if k in out["commodities"] and isinstance(v, dict):
            out["commodities"][k].update(v)
    for key in ("active_conflicts", "sanction_targets", "alliances"):
        if key in scenario:
            out[key] = scenario[key]
    return out
