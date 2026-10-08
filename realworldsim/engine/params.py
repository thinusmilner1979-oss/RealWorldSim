"""Tunable model parameters.

Everything that shapes the dynamics lives here so that contributors can tune the
model without touching the equations, and so that a parameter set can be saved
alongside a run for reproducibility. Rates are annual percentages unless noted;
the engine converts to daily increments internally.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass
class MacroParams:
    # Growth response to the real policy rate gap (pp of growth per pp of gap)
    rate_sensitivity: float = 0.25
    # Growth response to a 10% rise in the oil price, scaled by net import share of GDP
    oil_growth_elasticity: float = 0.6
    # Growth transmitted from trading partners (trade-weighted partner growth gap)
    trade_spillover: float = 0.25
    # Growth drag per unit of unrest / per unit of war intensity
    unrest_drag: float = 1.5
    war_drag_attacker: float = 2.0
    war_drag_defender: float = 9.0
    civil_war_drag: float = 6.0
    # Phillips-curve slope (inflation pp per pp of growth gap)
    phillips: float = 0.15
    # Commodity pass-through into inflation (pp per 10% oil/food move, by import share)
    oil_passthrough: float = 0.35
    food_passthrough: float = 0.25
    # FX pass-through (pp inflation per 10% depreciation)
    fx_passthrough: float = 0.5
    # Speed at which inflation returns to its anchor (per year)
    inflation_anchor_speed: float = 0.6
    # Monetary policy (Taylor rule): weights and smoothing
    taylor_inflation: float = 1.5
    taylor_output: float = 0.5
    rate_smoothing: float = 0.85  # monthly inertia
    # Okun coefficient: unemployment change per pp of growth gap
    okun: float = 0.4
    # Fiscal: automatic stabiliser (deficit pp per pp unemployment above trend)
    stabiliser: float = 0.5
    # Debt crisis threshold (debt/GDP %, before income-group adjustment)
    debt_crisis_threshold: float = 130.0
    # Base annual default hazard for fragile, indebted, inflationary states (at debt=100%, stability=0)
    default_base_hazard: float = 0.06
    # Random daily macro noise (annualised pp)
    growth_noise: float = 1.2
    inflation_noise: float = 0.6
    # FX: depreciation per pp inflation differential, risk premium weight
    fx_inflation: float = 1.0
    fx_risk: float = 6.0
    fx_rate_diff: float = 0.8


@dataclass
class CommodityParams:
    # Daily price adjustment per unit of (demand-supply)/supply
    oil_elasticity: float = 2.5
    gas_elasticity: float = 3.0
    food_elasticity: float = 1.5
    # Mean reversion toward long-run anchor (per year)
    oil_reversion: float = 0.12
    gas_reversion: float = 0.35
    food_reversion: float = 0.4
    metal_reversion: float = 0.3
    # Daily log-noise
    oil_noise: float = 0.02
    gas_noise: float = 0.025
    food_noise: float = 0.010
    metal_noise: float = 0.008
    gold_noise: float = 0.008
    # Share of a warring producer's output taken offline per unit of intensity
    war_output_loss: float = 0.35
    # Demand growth per pp of world growth (income elasticity)
    oil_income_elasticity: float = 0.5
    # Gas price link to oil (share of oil move passed to gas)
    gas_oil_link: float = 0.4
    # Fertilizer price link to gas
    fert_gas_link: float = 0.6
    # Gold response to global risk index
    gold_risk: float = 0.4


@dataclass
class GeoParams:
    # Mean reversion of tension to baseline (per year)
    tension_reversion: float = 0.5
    # Tension noise (daily std)
    tension_noise: float = 0.004
    # Tension pushed up by: sanctions, military build-up, ally-at-war, unrest spillover
    sanctions_tension: float = 0.08
    milspend_tension: float = 0.02
    ally_war_tension: float = 0.06
    # Trade dampens tension (per unit bilateral trade share)
    trade_damping: float = 0.4
    # War outbreak: base annual hazard at tension=threshold, logistic width
    war_hazard: float = 0.16
    war_threshold: float = 0.82
    war_width: float = 0.06
    nuclear_deterrence: float = 0.25  # multiply hazard if both nuclear
    democracy_peace: float = 0.4  # multiply hazard if both democracies
    # War dynamics
    escalation_drift: float = 0.0
    intensity_noise: float = 0.02
    ceasefire_base_hazard: float = 0.18  # annual, grows with duration and damage
    war_weariness: float = 0.3
    # Civil unrest
    unrest_decay: float = 0.9  # per year
    unrest_inflation: float = 0.015  # per pp inflation above 5
    unrest_unemployment: float = 0.01  # per pp unemployment above 8
    unrest_food: float = 0.02  # per 10% food price rise
    unrest_repression: float = 0.4  # autocracies suppress unrest
    unrest_noise: float = 0.01
    # Political crisis hazards (annual) when unrest high
    coup_hazard: float = 0.25
    gov_fall_hazard: float = 0.4
    civil_war_hazard: float = 0.16
    # Base rates independent of acute unrest (the world produces ~3 coups and ~3-5 sovereign
    # defaults a year even in calm times): annual hazard at full fragility
    coup_base_hazard: float = 0.12
    gov_fall_base_hazard: float = 0.10

    # Sanction effects
    sanction_growth: float = 3.0  # growth drag at 100% of trade sanctioned
    sanction_inflation: float = 4.0
    # Refugee outflow per unit intensity per year (share of population)
    refugee_rate: float = 0.03
    # Spillover of neighbour's war intensity into tension/unrest
    spillover: float = 0.05


@dataclass
class EventParams:
    # Annual hazards of exogenous shocks
    disaster_hazard: float = 1.5  # per year worldwide (scaled by exposure)
    pandemic_hazard: float = 0.05
    financial_crisis_hazard: float = 0.06
    tech_boom_hazard: float = 0.08
    drought_hazard: float = 0.6
    bumper_harvest_hazard: float = 0.6
    cyberattack_hazard: float = 0.5
    terror_hazard: float = 1.0


@dataclass
class Params:
    macro: MacroParams = field(default_factory=MacroParams)
    commodities: CommodityParams = field(default_factory=CommodityParams)
    geo: GeoParams = field(default_factory=GeoParams)
    events: EventParams = field(default_factory=EventParams)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Params:
        p = cls()
        for grp in fields(cls):
            sub = getattr(p, grp.name)
            for k, v in d.get(grp.name, {}).items():
                if hasattr(sub, k):
                    setattr(sub, k, v)
        return p
