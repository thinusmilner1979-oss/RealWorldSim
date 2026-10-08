"""Macroeconomic dynamics - one daily step for all countries at once.

The model is a deliberately simple, well-behaved reduced-form macro model:

  growth     <- potential growth
                - rate_sensitivity * (real policy rate - neutral)
                - oil shock * net import dependence
                + trade-weighted partner growth gap
                - drags from unrest, war, sanctions, debt crisis
  inflation  <- anchored to target, pushed by growth gap (Phillips), commodity
                pass-through, FX depreciation; anchor is weaker in unstable states
  policy rate<- Taylor rule with inertia (monthly), followed imperfectly by
                autocracies and crisis states
  unemployment <- Okun's law
  debt/GDP   <- deficit - growth erosion; deficit has structural, cyclical and
                war components
  fx         <- inflation differential vs USD, rate differential, risk premium

All rates are annual percentages; dt = 1/365.
"""
from __future__ import annotations

import numpy as np

from .params import MacroParams
from .world import World

DT = 1.0 / 365.0


class MacroState:
    """Scratch values that persist between ticks (lagged quantities)."""

    def __init__(self, world: World):
        self.prev_oil = world.prices["oil"]
        self.prev_food = world.prices["wheat"]
        self.prev_fx = world.s["fx"].copy()
        self.oil_shock = 0.0        # smoothed % change in oil price (annualised impulse)
        self.food_shock = 0.0
        self.day_in_month = 0
        self.debt_crisis = np.zeros(world.n, dtype=bool)
        self.crisis_days = np.zeros(world.n)
        # Markets tolerate what they already tolerate: a country stable today at 150% of GDP
        # (Japan, Singapore, Greece) is not in crisis at 151%. Threshold is the larger of the
        # structural threshold and 1.3x the starting level.
        self.debt_tolerance = world.s["debt_gdp"] * 1.3


def step_macro(world: World, p: MacroParams, st: MacroState, rng: np.random.Generator,
               events: list[dict], today) -> None:
    s = world.s
    n = world.n

    # ---- commodity impulses (smoothed daily log changes, expressed as % over ~1 month)
    oil_ret = np.log(world.prices["oil"] / st.prev_oil)
    food_ret = np.log(world.prices["wheat"] / st.prev_food)
    st.prev_oil, st.prev_food = world.prices["oil"], world.prices["wheat"]
    st.oil_shock = st.oil_shock * (1 - 1 / 30) + oil_ret * 100   # ~monthly cumulative % move
    st.food_shock = st.food_shock * (1 - 1 / 30) + food_ret * 100
    world._update_energy_balance(world.prices["oil"])

    # ---- growth ---------------------------------------------------------------
    real_rate_gap = (s["policy_rate"] - s["inflation"]) - (s["neutral_rate"] - s["inflation_target"])
    partner_gap = world.trade @ (s["growth"] - s["growth_trend"])
    # oil: sustained price level vs. the slowly adapting anchor hurts importers, helps exporters
    oil_level = np.log(world.prices["oil"] / world.price_anchor["oil"]) * 100  # % above anchor
    oil_term = np.clip(-p.oil_growth_elasticity * (oil_level / 10.0) * world.oil_import_gdp * 20, -6, 4)
    war = s["war_intensity"]
    sanction_drag = 3.0 * s["sanctioned_share"]
    crisis_drag = np.where(st.debt_crisis, 4.0, 0.0)
    world.exo_growth *= 1 - 4 * DT  # exogenous shocks fade with a ~3-month time constant
    target_growth = (
        s["growth_trend"]
        + world.exo_growth
        - p.rate_sensitivity * real_rate_gap
        + oil_term
        + p.trade_spillover * partner_gap
        - p.unrest_drag * np.maximum(s["unrest"] - 0.2, 0)
        - war_drag(world, p)
        - sanction_drag
        - crisis_drag
    )
    # growth adjusts toward target with a ~3-month half-life, plus noise
    noise = rng.normal(0, p.growth_noise, n) * np.sqrt(DT) * 3
    s["growth"] += (target_growth - s["growth"]) * (1 - np.exp(-DT * 4)) + noise
    s["growth"] = np.clip(s["growth"], -40, 25)

    # ---- inflation ------------------------------------------------------------
    gap = s["growth"] - s["growth_trend"]
    anchor_strength = p.inflation_anchor_speed * (0.4 + 0.6 * s["stability"]) * (1.2 - 0.6 * s["regime"])
    fx_ret = np.log(s["fx"] / st.prev_fx) * 100  # % depreciation today
    st.prev_fx = s["fx"].copy()
    import_share = np.clip(world.oil_import_gdp * 20 + 0.3, 0.1, 1.5)
    d_infl = (
        p.phillips * gap * DT * 4
        + p.oil_passthrough * (oil_ret * 100 / 10.0) * np.clip(world.oil_import_gdp * 30, 0, 1.5)
        + p.food_passthrough * (food_ret * 100 / 10.0) * s["food_import_share"]
        + p.fx_passthrough * (fx_ret / 10.0) * import_share * 0.5
        - anchor_strength * (s["inflation"] - s["inflation_target"]) * DT
        + rng.normal(0, p.inflation_noise, n) * np.sqrt(DT) * 2
    )
    # Monetised deficits in unstable states: inflation feeds on high debt + weak institutions
    monetise = (s["debt_gdp"] > 90) & (s["stability"] < 0.45)
    d_infl += np.where(monetise, 2.0 * DT * (s["deficit"] / 5.0), 0.0)
    s["inflation"] = np.clip(s["inflation"] + d_infl, -5, 1000)

    # ---- monetary policy (monthly decision) ----------------------------------
    st.day_in_month += 1
    if st.day_in_month >= 30:
        st.day_in_month = 0
        taylor = (
            s["neutral_rate"]
            + p.taylor_inflation * (s["inflation"] - s["inflation_target"])
            + p.taylor_output * gap
        )
        # Autocracies / unstable states follow the rule loosely and keep rates too low
        compliance = np.clip(0.5 + 0.5 * s["stability"] - 0.3 * s["regime"], 0.15, 1.0)
        desired = compliance * taylor + (1 - compliance) * (s["neutral_rate"] + 0.5 * s["inflation"])
        s["policy_rate"] = p.rate_smoothing * s["policy_rate"] + (1 - p.rate_smoothing) * desired
        s["policy_rate"] = np.clip(s["policy_rate"], -0.5, 500)

    # ---- unemployment (Okun) ------------------------------------------------
    s["unemployment"] += (-p.okun * gap * DT * 2
                          + (s["unemployment_trend"] - s["unemployment"]) * DT * 0.5)
    s["unemployment"] = np.clip(s["unemployment"], 0.5, 60)

    # ---- fiscal & debt --------------------------------------------------------
    structural = np.where(s["debt_gdp"] > 100, 2.0, 3.0)
    cyclical = p.stabiliser * (s["unemployment"] - s["unemployment_trend"])
    war_spend = 6.0 * war + 0.3 * np.maximum(s["mil_spend_gdp"] - 2.0, 0)
    interest = s["debt_gdp"] / 100.0 * np.maximum(s["policy_rate"], 0) * 0.6  # avg rate on debt lags policy
    s["deficit"] = 0.95 * s["deficit"] + 0.05 * (structural + cyclical + war_spend + interest * 0.5)
    nominal_growth = (s["growth"] + s["inflation"]) / 100.0
    s["debt_gdp"] += (s["deficit"] - s["debt_gdp"] * nominal_growth) * DT
    s["debt_gdp"] = np.clip(s["debt_gdp"], 0, 600)

    # Debt crisis: EM/frontier with high debt and high real rates, or any state above threshold
    group_adj = np.array([1.0 if g == "high_oecd" else 0.65 for g in world.income_group])
    threshold = np.maximum(p.debt_crisis_threshold * group_adj * (0.8 + 0.4 * s["stability"]), st.debt_tolerance)
    # high real rates and weak growth make a given debt level less sustainable
    snowball = np.clip((s["policy_rate"] - s["inflation"] - s["growth"]) / 5.0, -0.5, 1.0)
    stressed = (s["debt_gdp"] > threshold * (1 - 0.15 * snowball)) & ~st.debt_crisis
    hazard = np.where(stressed, 0.5 * DT * (s["debt_gdp"] / threshold - 0.8), 0.0)
    new_crisis = rng.random(n) < hazard
    for i in np.where(new_crisis)[0]:
        st.debt_crisis[i] = True
        st.crisis_days[i] = 0
        s["fx"][i] *= 1.25
        s["inflation"][i] += 6.0
        s["stability"][i] = max(0.05, s["stability"][i] - 0.1)
        events.append({"type": "debt_crisis", "country": world.iso[i], "severity": 0.7,
                       "text": f"{world.names[world.iso[i]]} slides into sovereign debt crisis; currency plunges"})
    st.crisis_days[st.debt_crisis] += 1
    # crises end after 1-3 years with a haircut
    ending = st.debt_crisis & (rng.random(n) < np.where(st.crisis_days > 365, DT * 0.7, 0.0))
    for i in np.where(ending)[0]:
        st.debt_crisis[i] = False
        s["debt_gdp"][i] *= 0.65
        events.append({"type": "debt_restructuring", "country": world.iso[i], "severity": 0.4,
                       "text": f"{world.names[world.iso[i]]} completes debt restructuring with creditors"})

    # ---- exchange rate --------------------------------------------------------
    usa = world.index.get("USA")
    us_infl = s["inflation"][usa] if usa is not None else 2.5
    us_rate = s["policy_rate"][usa] if usa is not None else 4.0
    risk = np.clip(0.5 * s["unrest"] + 2.0 * war + 0.6 * s["sanctioned_share"]
                   + np.where(st.debt_crisis, 0.5, 0) + 0.3 * (1 - s["stability"]), 0, 3)
    s["risk"] = risk / 3
    depreciation = (
        p.fx_inflation * (s["inflation"] - us_infl)
        - p.fx_rate_diff * ((s["policy_rate"] - s["inflation"]) - (us_rate - us_infl))
        + p.fx_risk * (risk - 0.3)
    ) * DT + rng.normal(0, 0.08, n) * np.sqrt(DT) * 2
    if usa is not None:
        depreciation[usa] = 0.0
    s["fx"] *= np.exp(np.clip(depreciation / 100.0, -0.2, 0.2))

    # ---- nominal GDP in USD ---------------------------------------------------
    # real growth + US inflation (world price level), adjusted for own FX move vs. inflation gap
    s["gdp"] *= 1 + (s["growth"] + us_infl) / 100.0 * DT
    s["gdp"] *= np.exp(-np.clip(depreciation, -50, 50) / 100.0 * 0.3)  # partial FX translation
    s["gdp"] = np.maximum(s["gdp"], 0.05)

    # ---- population -----------------------------------------------------------
    birth = np.array([1.0 if g in ("low", "lower_middle") else 0.6 if g == "upper_middle" else 0.3
                      for g in world.income_group])
    s["population"] *= 1 + (birth / 100.0 - 0.5 * war / 100.0) * DT

    # ---- stability slow dynamics ---------------------------------------------
    s["stability"] += (
        -0.15 * np.maximum(s["unrest"] - 0.3, 0) * DT * 4
        - 0.2 * war * DT * 4
        - 0.05 * np.maximum(s["inflation"] - 15, 0) / 10 * DT
        + 0.08 * (0.75 - s["stability"]) * DT  # slow drift back toward normal
        + 0.02 * np.maximum(gap, 0) * DT
    )
    s["stability"] = np.clip(s["stability"], 0.02, 0.98)


def war_drag(world: World, p: MacroParams) -> np.ndarray:
    """Growth drag from active conflicts, by role."""
    drag = np.zeros(world.n)
    for c in world.active_conflicts():
        ia, ib = world.index[c.a], world.index[c.b]
        if c.type == "civil":
            drag[ia] += p.civil_war_drag * c.intensity
        else:
            drag[ia] += p.war_drag_attacker * c.intensity
            drag[ib] += p.war_drag_defender * c.intensity
        for code in c.spillover:
            if code in world.index:
                drag[world.index[code]] += 1.5 * c.intensity
        for code in c.supporters_a + c.supporters_b:
            if code in world.index:
                drag[world.index[code]] += 0.2 * c.intensity
    return drag
