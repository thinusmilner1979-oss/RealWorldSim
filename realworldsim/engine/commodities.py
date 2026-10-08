"""Commodity markets: oil, gas, wheat, copper, gold, fertilizer.

Oil is modelled explicitly from country-level supply and demand:
  supply  = sum(oil_prod * (1 - war loss) * (1 - sanction loss)) * (1 - chokepoint closures) * (1 - user shock)
  demand  = sum(oil_cons) * f(world growth) * price elasticity
  d ln P  = elasticity * (demand - supply) / supply * dt - reversion * ln(P / anchor) * dt + noise

Gas follows a similar balance with a Europe-specific premium (TTF) that spikes when
Russian or Qatari supply or the relevant chokepoints are disrupted. Wheat reacts to
war in the breadbaskets (Ukraine, Russia), to fertilizer prices (gas-linked) and to
drought events. Copper tracks Chinese and world growth. Gold tracks global risk.
"""
from __future__ import annotations

import numpy as np

from .params import CommodityParams
from .world import World

DT = 1.0 / 365.0
BREADBASKETS = {"UKR": 0.10, "RUS": 0.20, "USA": 0.12, "CAN": 0.07, "AUS": 0.06, "FRA": 0.05,
                "ARG": 0.04, "IND": 0.05, "KAZ": 0.03}
GAS_TO_EUROPE = {"RUS": 0.25, "NOR": 0.30, "DZA": 0.10, "QAT": 0.10, "USA": 0.20}


class MarketState:
    """Persistent market state. On construction the markets are *calibrated*: today's
    prices are assumed to already clear today's supply and demand (including the losses
    from wars already under way), so only *changes* from the starting situation move
    prices."""

    def __init__(self, world: World, p: CommodityParams | None = None):
        p = p or CommodityParams()
        s = world.s
        self.world_growth = 3.0
        self.drought = 0.0        # 0..1 current drought severity in breadbaskets, decays
        self.disruption = {"oil": 0.0, "gas": 0.0, "gas_eu": 0.0}
        loss = war_loss(world, p)
        sanction_loss = 0.15 * s["sanctioned_share"]
        supply0 = float((s["oil_prod"] * (1 - loss) * (1 - sanction_loss)).sum())
        supply0 *= 1 - min(chokepoint_loss(world, "oil_share"), 0.9)  # today's observed shipping disruption
        self.demand_level = supply0 / max(float(s["oil_cons"].sum()), 1.0)  # oil demand multiplier
        self.demand_level0 = self.demand_level
        self.supply_level = 1.0   # slow-moving capacity: investment follows price, plus field growth
        gas_supply0 = float((s["gas_prod"] * (1 - loss) * (1 - 0.5 * sanction_loss)).sum())
        gas_supply0 *= 1 - min(chokepoint_loss(world, "gas_share"), 0.9)
        self.gas_demand_level = gas_supply0 / max(float(s["gas_cons"].sum()), 1.0)
        self.eu_loss0 = _eu_gas_loss(world, loss, s)
        self.bread_loss0 = _bread_loss(world, loss)
        self.base_disruption_oil = float(loss @ s["oil_prod"] / max(s["oil_prod"].sum(), 1))
        self.choke0 = chokepoint_loss(world, "oil_share")
        self.gchoke0 = chokepoint_loss(world, "gas_share")


def _eu_gas_loss(world: World, loss: np.ndarray, s: dict) -> float:
    return float(sum(share * (loss[world.index[c]] + 0.6 * s["sanctioned_share"][world.index[c]] * (c == "RUS"))
                     for c, share in GAS_TO_EUROPE.items() if c in world.index))


def _bread_loss(world: World, loss: np.ndarray) -> float:
    return float(sum(share * loss[world.index[c]] for c, share in BREADBASKETS.items() if c in world.index))


def chokepoint_loss(world: World, share_key: str) -> float:
    """Share of world seaborne supply lost to chokepoints: fully closed ones, or the disruption
    observed in shipping data (PortWatch) for open ones."""
    total = 0.0
    for cp in world.chokepoints.values():
        if cp["closed"]:
            total += cp[share_key]
        else:
            total += cp[share_key] * float(cp.get("observed_disruption", 0.0))
    return total


def war_loss(world: World, p: CommodityParams) -> np.ndarray:
    """Fraction of each country's output lost to war this day."""
    loss = np.zeros(world.n)
    for c in world.active_conflicts():
        for code, share in ((c.a, 1.0), (c.b, 1.0)):
            i = world.index[code]
            loss[i] = max(loss[i], p.war_output_loss * c.intensity * share)
        for code in c.spillover:
            if code in world.index:
                j = world.index[code]
                loss[j] = max(loss[j], 0.1 * c.intensity)
    return np.clip(loss, 0, 0.95)


def step_commodities(world: World, p: CommodityParams, ms: MarketState, rng: np.random.Generator,
                     events: list[dict]) -> None:
    s = world.s
    w = world.gdp_weights()
    ms.world_growth = float((s["growth"] * w).sum())

    loss = war_loss(world, p)
    # Sanctions reduce how much a producer can actually sell (friction, discounts) - mild
    sanction_loss = 0.15 * s["sanctioned_share"]

    # ---- oil ---------------------------------------------------------------
    supply = float((s["oil_prod"] * (1 - loss) * (1 - sanction_loss)).sum())
    choke = chokepoint_loss(world, "oil_share")
    supply *= (1 - min(choke, 0.9)) * (1 - world.oil_supply_shock)
    # capacity grows ~0.8%/yr plus investment response to a sustained price gap
    ms.supply_level *= 1 + (0.008 + 0.04 * np.log(world.prices["oil"] / world.price_start["oil"])) * DT
    supply *= ms.supply_level
    # demand: slow income effect + price elasticity (-0.1 short run)
    ms.demand_level *= 1 + (p.oil_income_elasticity * ms.world_growth / 100.0) * DT
    price_ratio = world.prices["oil"] / world.price_anchor["oil"]
    # short-run price elasticities: demand -0.15, supply +0.10 (shale, OPEC spare capacity)
    demand = float(s["oil_cons"].sum()) * ms.demand_level * price_ratio ** -0.15
    supply *= price_ratio ** 0.10
    imbalance = (demand - supply) / max(supply, 1.0)
    ms.disruption["oil"] = float(np.clip(loss @ s["oil_prod"] / max(s["oil_prod"].sum(), 1)
                                         - ms.base_disruption_oil + choke - ms.choke0 + world.oil_supply_shock, 0, 1))
    d = (p.oil_elasticity * imbalance * DT * 30     # ~monthly clearing speed
         - p.oil_reversion * np.log(price_ratio) * DT
         + rng.normal(0, p.oil_noise))
    world.prices["oil"] *= float(np.exp(np.clip(d, -0.2, 0.25)))
    # the anchor itself drifts slowly toward actual price (structural change sticks)
    world.price_anchor["oil"] *= np.exp(0.15 * np.log(price_ratio) * DT)
    world.prices["oil"] = float(np.clip(world.prices["oil"], 8, 600))

    # ---- gas -----------------------------------------------------------------
    gas_supply = float((s["gas_prod"] * (1 - loss) * (1 - 0.5 * sanction_loss)).sum())
    gchoke = chokepoint_loss(world, "gas_share")
    gas_supply *= 1 - min(gchoke, 0.9)
    gas_ratio = world.prices["gas"] / world.price_anchor["gas"]
    gas_demand = (float(s["gas_cons"].sum()) * ms.gas_demand_level
                  * (ms.demand_level / ms.demand_level0) * gas_ratio ** -0.15)
    gas_supply *= gas_ratio ** 0.08
    g_imb = (gas_demand - gas_supply) / max(gas_supply, 1.0)
    oil_ret = d  # today's oil log move
    dg = (p.gas_elasticity * g_imb * DT * 30
          - p.gas_reversion * np.log(world.prices["gas"] / world.price_anchor["gas"]) * DT
          + p.gas_oil_link * oil_ret * 0.5
          + rng.normal(0, p.gas_noise))
    world.prices["gas"] *= float(np.exp(np.clip(dg, -0.25, 0.3)))
    world.prices["gas"] = float(np.clip(world.prices["gas"], 0.8, 80))

    # European gas: hub price plus premium driven by disruption of Europe's suppliers
    eu_loss = _eu_gas_loss(world, loss, s) - ms.eu_loss0
    ms.disruption["gas_eu"] = float(np.clip(eu_loss + gchoke - ms.gchoke0, -1, 1))
    eu_ratio0 = world.price_start["gas_eu"] / world.price_start["gas"]
    eu_target = world.prices["gas"] * eu_ratio0 * (1 + 4.0 * ms.disruption["gas_eu"])
    world.prices["gas_eu"] += (eu_target - world.prices["gas_eu"]) * (1 - np.exp(-DT * 12))
    world.prices["gas_eu"] *= float(np.exp(rng.normal(0, p.gas_noise * 0.8)))
    world.prices["gas_eu"] = float(np.clip(world.prices["gas_eu"], 3, 400))

    # ---- fertilizer (gas-linked) ---------------------------------------------
    fert_target = world.price_anchor["fertilizer"] * (world.prices["gas"] / world.price_start["gas"]) ** p.fert_gas_link
    world.prices["fertilizer"] += (fert_target - world.prices["fertilizer"]) * (1 - np.exp(-DT * 6))
    world.prices["fertilizer"] *= float(np.exp(rng.normal(0, p.metal_noise * 0.7)))

    # ---- wheat / food ---------------------------------------------------------
    bread_loss = _bread_loss(world, loss) - ms.bread_loss0   # change vs. the starting situation
    ms.drought *= 1 - 2.0 * DT  # droughts fade over ~6 months
    fert_ret = np.log(world.prices["fertilizer"] / world.price_anchor["fertilizer"])
    food_ratio = world.prices["wheat"] / world.price_anchor["wheat"]
    # supply shortfall vs. price response of demand/supply (self-limiting)
    food_imb = bread_loss + 0.25 * ms.drought + 0.15 * fert_ret - 0.3 * np.log(food_ratio)
    dw = (p.food_elasticity * food_imb * DT * 12
          - p.food_reversion * np.log(food_ratio) * DT
          + rng.normal(0, p.food_noise))
    world.prices["wheat"] *= float(np.exp(np.clip(dw, -0.15, 0.2)))
    world.prices["wheat"] = float(np.clip(world.prices["wheat"], 2, 40))

    # ---- copper (industrial demand) ------------------------------------------
    chn = world.index.get("CHN")
    ind_growth = 0.5 * ms.world_growth + 0.5 * (s["growth"][chn] if chn is not None else ms.world_growth)
    dc = (0.04 * (ind_growth - 3.0) * DT
          - p.metal_reversion * np.log(world.prices["copper"] / world.price_anchor["copper"]) * DT
          + rng.normal(0, p.metal_noise))
    world.prices["copper"] *= float(np.exp(dc))
    world.prices["copper"] = float(np.clip(world.prices["copper"], 1, 30))

    # ---- gold (risk) ------------------------------------------------------------
    risk = world.global_risk()
    if world.risk0 is None:
        world.risk0 = risk
    risk = risk - world.risk0 + 0.35  # gold reacts to changes in risk vs. the starting world
    us = world.index.get("USA")
    us_real = (s["policy_rate"][us] - s["inflation"][us]) if us is not None else 1.0
    gold_ratio = world.prices["gold"] / world.price_anchor["gold"]
    dgold = (p.gold_risk * (risk - 0.35) * DT * 2
             - 0.03 * us_real * DT
             + 0.03 * DT  # secular drift
             - 0.2 * np.log(gold_ratio) * DT
             + rng.normal(0, p.gold_noise))
    world.prices["gold"] *= float(np.exp(dgold))
    world.price_anchor["gold"] *= np.exp(0.25 * np.log(gold_ratio) * DT)
    world.prices["gold"] = float(np.clip(world.prices["gold"], 500, 50000))
