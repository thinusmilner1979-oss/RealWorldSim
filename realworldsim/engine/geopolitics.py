"""Geopolitics: tension, war, unrest, sanctions, refugees.

Tension is a symmetric N x N matrix in [0, 1]. Each day it:
  * reverts toward its structural baseline (rivalries, geography, alliances),
  * rises with sanctions, military build-ups, an ally being at war with the other side,
    and spill-over from nearby conflicts,
  * falls with bilateral trade,
  * gets noise.

War breaks out stochastically when tension is high (logistic hazard), damped by nuclear
deterrence and the democratic peace. Active wars random-walk in intensity with a
ceasefire hazard that rises with duration and economic damage. Civil unrest is a per-
country index driven by inflation, unemployment, food prices and repression; when it is
high, governments fall, coups happen, or civil wars start.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from .params import GeoParams
from .world import Conflict, World

DT = 1.0 / 365.0


class GeoState:
    def __init__(self, world: World):
        self.prev_food = world.prices["wheat"]
        self.counter = 0
        self.last_gov_change = np.full(world.n, 400.0)  # days since last government change
        # what people are used to: unrest responds to deterioration, not to chronic levels
        self.infl_ref = world.s["inflation"].copy()
        self.unemp_ref = world.s["unemployment"].copy()
        # structural unrest floor: fragile states and restless democracies never fully calm down
        s = world.s
        self.unrest_floor = np.maximum(0.05 + 0.3 * (1 - s["stability"]) * (1 - 0.5 * s["regime"]),
                                       0.6 * s["unrest"])


def _hazard(annual: float | np.ndarray) -> float | np.ndarray:
    """Convert an annual hazard rate into a daily probability."""
    return 1.0 - np.exp(-np.asarray(annual) * DT)


def step_geopolitics(world: World, p: GeoParams, gs: GeoState, rng: np.random.Generator,
                     events: list[dict], today: date) -> None:
    s = world.s
    n = world.n
    gs.counter += 1
    gs.last_gov_change += 1

    # ---- war exposure per country --------------------------------------------
    war = np.zeros(n)
    for c in world.active_conflicts():
        ia, ib = world.index[c.a], world.index[c.b]
        war[ia] = max(war[ia], c.intensity)
        war[ib] = max(war[ib], c.intensity)
        for code in c.spillover:
            if code in world.index:
                k = world.index[code]
                war[k] = max(war[k], 0.3 * c.intensity)
    s["war_intensity"] = war

    # ---- tension dynamics ----------------------------------------------------
    T = world.tension
    base = world.tension_base
    dT = p.tension_reversion * (base - T) * DT
    # sanctions push tension both ways
    sanc = np.maximum(world.sanctions, world.sanctions.T)
    dT += p.sanctions_tension * sanc * DT
    # military build-up: countries whose spending is high raise neighbours'/rivals' tension
    mil = np.clip(s["mil_spend_gdp"] - 2.5, 0, 10) / 10
    dT += p.milspend_tension * (mil[:, None] + mil[None, :]) * (T > 0.3) * DT
    # ally at war: if i is allied with a, and a fights b, tension(i, b) rises
    for c in world.active_conflicts():
        if c.type == "civil":
            continue
        ia, ib = world.index[c.a], world.index[c.b]
        for side, enemy in ((ia, ib), (ib, ia)):
            # allies' tension with the enemy rises, but saturates below open hostility
            allies = world.alliance[side] * c.intensity * p.ally_war_tension * DT * (T[:, enemy] < 0.85)
            dT[:, enemy] += allies
            dT[enemy, :] += allies
        for code in c.supporters_a:
            if code in world.index:
                k = world.index[code]
                dT[k, ib] += 0.3 * c.intensity * DT
                dT[ib, k] += 0.3 * c.intensity * DT
        for code in c.supporters_b:
            if code in world.index:
                k = world.index[code]
                dT[k, ia] += 0.3 * c.intensity * DT
                dT[ia, k] += 0.3 * c.intensity * DT
    # trade dampens
    trade_sym = (world.trade + world.trade.T) / 2
    dT -= p.trade_damping * trade_sym * (T - 0.1) * DT
    # spill-over from neighbours at war (border tension)
    near = (world.distance < 1200).astype(float)
    dT += p.spillover * (near * war[None, :]) * DT
    # noise, scaled so distant irrelevant pairs barely move
    relevance = np.clip(base * 3 + near * 0.5, 0.1, 1.0)
    noise = rng.normal(0, p.tension_noise, (n, n)) * relevance
    noise = (noise + noise.T) / 2
    T += dT + noise
    T = (T + T.T) / 2
    np.fill_diagonal(T, 0.0)
    world.tension = np.clip(T, 0.0, 1.0)

    # ---- war outbreak ----------------------------------------------------------
    at_war = np.zeros((n, n), dtype=bool)
    for c in world.active_conflicts():
        if c.type != "civil":
            ia, ib = world.index[c.a], world.index[c.b]
            at_war[ia, ib] = at_war[ib, ia] = True
    logistic = 1 / (1 + np.exp(-(world.tension - p.war_threshold) / p.war_width))
    hazard = p.war_hazard * logistic
    nuc = world.nuclear
    both_nuc = np.outer(nuc, nuc)
    hazard = np.where(both_nuc, hazard * p.nuclear_deterrence, hazard)
    # extended deterrence: attacking a close ally of a nuclear power is much less likely
    umbrella = (world.alliance[:, nuc] * 1.0).max(axis=1) if nuc.any() else np.zeros(n)  # strength of best nuclear ally
    shield = 1 - 0.8 * np.clip(umbrella, 0, 1)
    hazard = hazard * np.minimum(shield[:, None], shield[None, :])
    dem = s["regime"] < 0.35
    hazard = np.where(np.outer(dem, dem), hazard * p.democracy_peace, hazard)
    # only plausible for neighbours or great-power rivalries (projection capability ~ GDP)
    reach = (world.distance < 2500) | (np.minimum.outer(s["gdp"], s["gdp"]) > 800)
    # military balance: wars start when one side expects to win; peers deter each other
    mp = np.maximum(s["mil_power"], 1e-3)
    share = mp[:, None] / (mp[:, None] + mp[None, :])
    dominance = np.abs(share - 0.5) * 2  # 0 = peers, 1 = total mismatch
    hazard = hazard * (1 - p.dominance_hazard / 2 + p.dominance_hazard * dominance)
    hazard = np.where(reach & ~at_war, hazard, 0.0)
    hazard = np.triu(hazard, 1)
    draws = rng.random((n, n)) < _hazard(hazard)
    for ia, ib in zip(*np.where(draws), strict=True):
        # aggressor: the more autocratic side, unless it is hopelessly outgunned
        if s["regime"][ib] > s["regime"][ia] and s["mil_power"][ib] > 0.3 * s["mil_power"][ia]:
            ia, ib = ib, ia
        elif s["mil_power"][ia] < 0.3 * s["mil_power"][ib]:
            ia, ib = ib, ia
        a, b = world.iso[ia], world.iso[ib]
        intensity = float(np.clip(rng.normal(0.35, 0.15), 0.1, 0.8))
        cid = f"{a.lower()}_{b.lower()}_{today.year}"
        world.conflicts.append(Conflict(id=cid, name=f"{world.names[a]}–{world.names[b]} war", a=a, b=b,
                                        intensity=intensity, started=today, type="interstate", peak=intensity))
        events.append({"type": "war_start", "country": a, "country2": b, "severity": 0.9 + 0.1 * intensity,
                       "text": f"WAR: {world.names[a]} launches attack on {world.names[b]}"})
        # treaty allies of the defender join as supporters (arms, intelligence, sanctions)
        conflict = world.conflicts[-1]
        conflict.supporters_b = [world.iso[k] for k in np.where(world.alliance[ib] >= 0.8)[0] if k != ia]
        conflict.supporters_a = [world.iso[k] for k in np.where(world.alliance[ia] >= 0.8)[0] if k != ib]
        if conflict.supporters_b:
            events.append({"type": "alliance", "country": b, "severity": 0.7,
                           "text": f"Allies of {world.names[b]} pledge military support against {world.names[a]}"})
        # allies of the defender sanction the aggressor (democracies do, mostly)
        for k in np.where(world.alliance[ib] > 0.5)[0]:
            if s["regime"][k] < 0.5 and k != ia:
                world.sanctions[k, ia] = max(world.sanctions[k, ia], 0.7)
        world.update_sanctioned_share()

    # ---- war evolution ----------------------------------------------------------
    for c in world.active_conflicts():
        c.days += 1
        ia, ib = world.index[c.a], world.index[c.b]
        if c.type != "civil":
            t = world.tension[ia, ib]
            target = float(np.clip((t - 0.5) * 1.4, 0.05, 1.0))  # tension 0.85 -> ~0.5; 0.95 -> 0.63
            # deliberate escalation to full-scale war: rare unless tension is extreme
            if not c.major:
                hz = p.escalation_hazard / (1 + np.exp(-(t - p.escalation_threshold) / p.escalation_width))
                if rng.random() < _hazard(hz):
                    c.intensity = float(np.clip(rng.normal(0.8, 0.1), 0.6, 1.0))
        else:
            target = float(np.clip(0.3 + 0.5 * (1 - s["stability"][ia]), 0.1, 0.9))
        drift = p.intensity_reversion * (target - c.intensity) * DT
        # exhaustion: long high-intensity wars decay
        drift -= p.war_weariness * c.intensity * (c.days / 365.0) * DT
        c.intensity = float(np.clip(c.intensity + drift + rng.normal(0, p.intensity_noise), 0.02, 1.0))
        c.peak = max(c.peak, c.intensity)
        # crossing into major war is an event in its own right (Donbas 2014 -> invasion 2022)
        if not c.major and c.intensity >= 0.6:
            c.major = True
            if c.days > 30:
                events.append({"type": "war_escalation", "country": c.a, "country2": c.b, "severity": 0.9,
                               "text": f"{c.name} escalates into full-scale war"})
        elif c.major and c.intensity < 0.35:
            c.major = False
        elif c.intensity > c.peak - 1e-9 and c.intensity > 0.6 and rng.random() < 0.01:
            events.append({"type": "escalation", "country": c.a, "country2": c.b, "severity": 0.7,
                           "text": f"{c.name} escalates sharply"})
        # decisive outcome: the stronger side can win outright; more likely the bigger the mismatch
        if c.type != "civil" and c.major:  # frozen conflicts are not decided; full-scale wars can be
            pa, pb = max(s["mil_power"][ia], 1e-3), max(s["mil_power"][ib], 1e-3)
            share_a = pa / (pa + pb)
            mismatch = abs(share_a - 0.5) * 2
            hz_dec = p.decisive_hazard * mismatch ** 2 * c.intensity ** 2 * min(c.days / 180.0, 2.0)
            if rng.random() < _hazard(hz_dec):
                winner, loser = (ia, ib) if rng.random() < share_a else (ib, ia)
                c.ended = today
                c.outcome = f"{world.iso[winner]} victory"
                s["stability"][loser] = max(0.05, s["stability"][loser] - 0.2)
                s["unrest"][loser] = min(1.0, s["unrest"][loser] + 0.25)
                s["stability"][winner] = min(0.98, s["stability"][winner] + 0.05)
                world.exo_growth[loser] -= 4.0 * c.intensity
                world.tension[ia, ib] = world.tension[ib, ia] = 0.5
                world.tension_base[ia, ib] = world.tension_base[ib, ia] = max(world.tension_base[ia, ib] * 0.8, 0.35)
                events.append({"type": "war_end", "country": world.iso[winner], "country2": world.iso[loser],
                               "severity": 0.8, "text": f"{c.name} ends in {world.names[world.iso[winner]]} victory; "
                                                        f"{world.names[world.iso[loser]]} capitulates"})
                continue
        # ceasefire hazard grows with duration and damage, falls with intensity momentum
        damage = (s["unrest"][ia] + s["unrest"][ib]) / 2 + 0.3 * min(c.days / 365.0, 3) / 3
        hz = p.ceasefire_base_hazard * (0.3 + damage) * (1.3 - c.intensity)
        if c.type == "civil":
            hz *= 0.5
        if rng.random() < _hazard(hz):
            c.ended = today
            if c.type != "civil":
                world.tension[ia, ib] = world.tension[ib, ia] = min(world.tension[ia, ib], 0.6)
                world.tension_base[ia, ib] = world.tension_base[ib, ia] = max(world.tension_base[ia, ib] * 0.9, 0.3)
            events.append({"type": "ceasefire", "country": c.a, "country2": c.b, "severity": 0.6,
                           "text": f"Ceasefire: {c.name} ends after {c.days // 30} months"})
            continue
        # major interstate wars can draw in supporters' sanctions and raise mil spending
        s["mil_spend_gdp"][ia] += 0.6 * c.intensity * DT * 4
        s["mil_spend_gdp"][ib] += 1.5 * c.intensity * DT * 4
        # refugees: defender/civil war population flees to neighbours
        victim = ib if c.type != "civil" else ia
        flow = s["population"][victim] * p.refugee_rate * c.intensity * DT
        s["refugees_out"][victim] += flow
        nb = world.neighbours(victim, 1500)
        if len(nb):
            weights = np.exp(-world.distance[victim, nb] / 800) * (1 + s["stability"][nb])
            weights /= weights.sum()
            s["refugees_in"][nb] += flow * weights
            s["unrest"][nb] += 0.02 * c.intensity * DT * weights * 10
    # military spending relaxes toward baseline when at peace
    s["mil_spend_gdp"] += (np.where(war > 0, 0, 1) * (1.8 - s["mil_spend_gdp"]) * 0.05) * DT
    s["mil_spend_gdp"] = np.clip(s["mil_spend_gdp"], 0.1, 40)
    if gs.counter % 30 == 0:
        world.update_military_power()

    # ---- civil unrest ----------------------------------------------------------
    food_ret = np.log(world.prices["wheat"] / gs.prev_food) * 100
    gs.prev_food = world.prices["wheat"]
    u = s["unrest"]
    # reference levels adapt slowly (~3 years): people get used to chronic conditions
    gs.infl_ref += (s["inflation"] - gs.infl_ref) * DT / 3
    gs.unemp_ref += (s["unemployment"] - gs.unemp_ref) * DT / 3
    infl_surprise = np.maximum(s["inflation"] - gs.infl_ref, 0) + 0.15 * np.maximum(s["inflation"] - 20, 0)
    unemp_surprise = np.maximum(s["unemployment"] - gs.unemp_ref, 0) + 0.1 * np.maximum(s["unemployment"] - 15, 0)
    du = (
        -p.unrest_decay * (u - gs.unrest_floor) * DT
        + p.unrest_inflation * infl_surprise * DT * 2
        + p.unrest_unemployment * unemp_surprise * DT * 2
        + p.unrest_food * (food_ret / 10.0) * s["food_import_share"] * 0.3
        + 0.15 * np.maximum(-s["growth"], 0) / 10 * DT * 4
        + 0.2 * war * DT
        + p.drought_unrest * np.maximum(s["drought"], 0) * DT * 4
        + rng.normal(0, p.unrest_noise, n) * np.sqrt(DT) * 4
    )
    du = np.where(du > 0, du * (1.1 - u), du)  # harder to push unrest toward saturation
    # repression: autocracies suppress visible unrest but it builds pressure in stability
    du -= p.unrest_repression * s["regime"] * np.maximum(u - 0.2, 0) * DT * 2
    s["unrest"] = np.clip(u + du, 0.0, 1.0)

    # ---- political crises -----------------------------------------------------
    high = np.maximum(s["unrest"] - 0.5, 0) / 0.5
    fragility = (1 - s["stability"]) ** 2
    # government falls (democracies): protests, no-confidence, snap election - plus a base rate
    gov = _hazard((p.gov_fall_hazard * high + p.gov_fall_base_hazard * (0.3 + 2 * s["unrest"]) * (1 - s["stability"]))
                  * (1 - s["regime"]) * (gs.last_gov_change > 120))
    # coups: acute unrest in autocracies, plus a base rate in fragile autocracies / hybrids
    coup = _hazard((p.coup_hazard * high * (1.2 - s["stability"])
                    + p.coup_base_hazard * fragility * (0.5 + s["unrest"]))
                   * np.clip(s["regime"], 0.1, 1) * (gs.last_gov_change > 180))
    civil = _hazard(p.civil_war_hazard * high ** 2 * (1 - s["stability"]) * (war == 0))
    r = rng.random((3, n))
    for i in np.where(r[0] < gov)[0]:
        code = world.iso[i]
        gs.last_gov_change[i] = 0
        s["unrest"][i] *= 0.6
        s["stability"][i] = max(0.05, s["stability"][i] - 0.05)
        if s["regime"][i] < 0.5:
            text = f"Government of {world.names[code]} collapses amid mass protests; snap elections called"
        else:
            text = f"Leadership of {world.names[code]} reshuffled under pressure from nationwide protests"
        events.append({"type": "government_falls", "country": code, "severity": 0.6, "text": text})
    for i in np.where(r[1] < coup)[0]:
        code = world.iso[i]
        gs.last_gov_change[i] = 0
        s["unrest"][i] *= 0.5
        s["stability"][i] = max(0.05, s["stability"][i] - 0.2)
        s["regime"][i] = min(1.0, s["regime"][i] + 0.1)
        events.append({"type": "coup", "country": code, "severity": 0.8,
                       "text": f"Military coup in {world.names[code]}; constitution suspended"})
        # democracies sanction coup regimes lightly
        for k in np.where((s["regime"] < 0.3) & (s["gdp"] > 300))[0]:
            world.sanctions[k, i] = max(world.sanctions[k, i], 0.3)
        world.update_sanctioned_share()
    for i in np.where(r[2] < civil)[0]:
        code = world.iso[i]
        intensity = float(np.clip(rng.normal(0.4, 0.15), 0.1, 0.8))
        world.conflicts.append(Conflict(id=f"civil_{code.lower()}_{today.year}",
                                        name=f"{world.names[code]} civil war", a=code, b=code,
                                        intensity=intensity, started=today, type="civil", peak=intensity))
        events.append({"type": "civil_war", "country": code, "severity": 0.9,
                       "text": f"Civil war erupts in {world.names[code]}"})

    # ---- sanctions relax slowly when tension is low and no war -----------------
    relax = (world.tension < 0.45) & (world.sanctions > 0) & ~at_war
    world.sanctions[relax] *= 1 - 0.1 * DT
    world.sanctions[world.sanctions < 0.02] = 0.0
    if gs.counter % 30 == 0:
        world.update_sanctioned_share()

    # ---- chokepoints: controllers at high-intensity war may close them -----------
    for cp in world.chokepoints.values():
        ctrl = [world.index[c] for c in cp["controllers"] if c in world.index]
        hot = max((war[k] for k in ctrl), default=0.0)
        if not cp["closed"] and hot > 0.5 and rng.random() < _hazard(1.5 * hot):
            cp["closed"] = True
            cp["closed_by"] = "conflict"
            events.append({"type": "chokepoint_closed", "country": cp["controllers"][0], "severity": 0.9,
                           "text": f"{cp['name']} closed to shipping as fighting spreads"})
        elif cp["closed"] and cp.get("closed_by") == "conflict" and hot < 0.3 and rng.random() < _hazard(3.0):
            cp["closed"] = False
            events.append({"type": "chokepoint_open", "country": cp["controllers"][0], "severity": 0.5,
                           "text": f"{cp['name']} reopens to shipping"})
