# Roadmap

Phases, roughly in order. Each bullet is meant to become a GitHub issue; claim one by commenting on it.

## 0.1 — the first slice (done)
- [x] Engine with every country, daily tick, deterministic seeds
- [x] Macro, commodities, geopolitics, exogenous events
- [x] Live sync from World Bank / UCDP / GDELT / FRED
- [x] Web UI: map, charts, wire, time control, interventions, save/load
- [x] Docs, tests, Mint launcher

## 0.2 — believe it a little more
- [ ] **Backtest harness**: initialise at 2015-01-01 from World Bank/UCDP history, run to today, score coverage of actual GDP/inflation/oil paths and conflict onsets (Brier score). Make it `rws backtest`.
- [ ] **Ensemble mode**: `rws ensemble --runs 100` producing fan charts and event probabilities ("P(ceasefire in Ukraine by 2027)"); UI view for it.
- [ ] Trade matrix from real bilateral data (UN Comtrade / CEPII BACI) instead of gravity
- [ ] Policy rates from BIS; IMF WEO forecasts as the growth-trend prior
- [ ] Oil/gas production & consumption for all countries from EIA / Our World in Data
- [ ] Military spending from SIPRI; nuclear status from a maintained list
- [ ] Replace the hand-curated `overrides.json` with sourced, dated values wherever a free source exists

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
