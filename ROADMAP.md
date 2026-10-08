# Roadmap

Phases, roughly in order. Each bullet is meant to become a GitHub issue; claim one by commenting on it.

## 0.1 — the first slice (done)
- [x] Engine with every country, daily tick, deterministic seeds
- [x] Macro, commodities, geopolitics, exogenous events
- [x] Live sync from World Bank / UCDP / GDELT / FRED
- [x] Web UI: map, charts, wire, time control, interventions, save/load
- [x] Docs, tests, Mint launcher

## 0.2 — believe it a little more
- [x] **Backtest harness**: `rws backtest` — 2015 start state, parallel ensemble, scored against a 2015–2025 scorecard (see docs/BACKTESTING.md). Baseline composite 0.53.
- [ ] Backtest-driven fixes, biggest first: a pandemic/stimulus inflation channel; OPEC and demand shocks for oil; reserves + external debt + IMF for defaults; insurgent groups as actors
- [ ] More start years (2000, 2008) and a scorecard for each; country-level scoring for all countries from World Bank history
- [ ] **Ensemble mode**: `rws ensemble --runs 100` producing fan charts and event probabilities ("P(ceasefire in Ukraine by 2027)"); UI view for it.
- [ ] Trade matrix from real bilateral data (UN Comtrade / CEPII BACI) instead of gravity
- [ ] Policy rates from BIS; IMF WEO forecasts as the growth-trend prior
- [ ] Oil/gas production & consumption for all countries from EIA / Our World in Data
- [ ] Military spending from SIPRI; nuclear status from a maintained list
- [ ] Replace the hand-curated `overrides.json` with sourced, dated values wherever a free source exists

## Next up (agreed 2026-10-08)
- [ ] **War motives, fitted from history.** Replace "tension + expected win" with generic motive terms for every
      country, each with a coefficient in `params.py`: diversionary (recession, unrest, falling legitimacy →
      external fight), resource security (energy/food import dependence under supply shock or chokepoint
      pressure; exporters defending markets), economic stakes (trade dampens; relative decline → "window"),
      systemic/currency interest (reserve-currency issuers when financial dominance erodes), opportunity
      (rival distracted or weakened). Fit the weights against UCDP / Correlates of War initiators + World Bank
      economic state at onset, keyless bulk data. Report what the data says — including terms that come out ~0.
- [ ] **War endings, fitted from history.** Survival model for ceasefire/decisive-end hazard on UCDP conflict
      durations: duration, intensity, war type, balance of forces.
- [ ] Sync runs in a separate process so the simulation never slows during a sync.

## 0.3 — governments that decide things
- [ ] Per-country **agent** with a personality vector (hawkishness, fiscal discipline, openness, repression) derived from V-Dem / Polity / Economist indices
- [ ] Monthly action set: rates, fiscal stance, arm, ally, sanction, escalate, de-escalate, negotiate, mobilise
- [ ] Elections and leadership changes with policy shifts
- [ ] Alliance dynamics: joining, leaving, collective defence actually triggering
- [ ] Peace processes with mediators; frozen conflicts

## 0.4 — richer world
- [ ] Demographics (age structure, migration, fertility transitions)
- [ ] Climate: slow trend damage + rising disaster hazard; energy transition reducing oil demand elasticity
- [ ] Technology/productivity shocks by sector; AI diffusion as a growth driver
- [ ] Financial contagion through a banking/credit layer; sovereign spreads
- [ ] Domestic politics: polarisation, populism, legitimacy
- [ ] Sub-national: regions for the biggest states (optional, expensive)

## 0.5 — learning
- [ ] Fit agent policies to historical decisions (gradient-boosted or small nets)
- [ ] Parameter estimation via simulated method of moments against the backtest
- [ ] GPU ensemble runner (batched numpy/torch) for 10k-run distributions

## Always
- [ ] More tests, better calibration, clearer docs
- [ ] UI polish: timeline scrubbing, scenario diffing, mobile layout, accessibility (table views for every chart)
