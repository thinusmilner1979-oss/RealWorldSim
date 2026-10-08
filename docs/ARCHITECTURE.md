# Architecture

RealWorldSim is three things stacked on top of each other:

```
┌──────────────────────────────────────────────────────────────┐
│  UI  (server/static)   map · charts · wire · controls         │
├──────────────────────────────────────────────────────────────┤
│  Server (server/app.py)  FastAPI · websocket · clock · API    │
├──────────────────────────────────────────────────────────────┤
│  Engine (engine/)                                             │
│    Simulation  ─ owns a World, steps it, records history      │
│    World       ─ state: N countries × fields, N×N matrices    │
│    economy · commodities · geopolitics · events  (dynamics)   │
│    params      ─ every tunable constant                        │
├──────────────────────────────────────────────────────────────┤
│  Data (data/, sync/)   bundled seed · live fetchers · cache   │
└──────────────────────────────────────────────────────────────┘
```

The engine has **no dependency on the server**; `rws run` and the test-suite drive it headless. Anything that makes the model better goes in `engine/`; anything that makes it nicer to look at goes in `server/static/`.

## State

`World` holds, for N ≈ 195 countries, a dict of numpy arrays `world.s[field]` (see `COUNTRY_FIELDS` in `engine/world.py`): GDP, population, growth, potential growth, inflation and its target, unemployment and its trend, policy and neutral rates, debt/GDP, deficit, FX index, stability, regime, unrest, military spending, oil and gas production/consumption, food import share, war exposure, sanctioned trade share, refugees, risk premium.

Plus pairwise matrices: `distance` (great-circle km from label points), `alliance` (0..1 from membership lists with per-bloc weights), `trade` (row-normalised gravity model: GDP·GDP / distance^1.1, ×1.5 for allies), `tension_base` (structural baseline), `tension` (current), `sanctions[i, j]` (i sanctions j).

Plus markets (`prices`, `price_anchor`, `price_start`), chokepoints, a list of `Conflict` objects, and `exo_growth` (a decaying exogenous growth gap that events write to).

Everything is **vectorised**: one daily tick is a handful of numpy operations on arrays of length N and N×N, plus Python loops only over the (few) active conflicts and events. Ten simulated years take about 15 s on a laptop core.

## The daily tick

`Simulation.step()` runs, in order:

1. `step_geopolitics` – war exposure, tension update, war outbreak, war evolution and ceasefires, refugees, unrest, political crises, sanctions decay, chokepoint closures.
2. `step_commodities` – oil, gas, European gas, fertilizer, wheat, copper, gold.
3. `step_macro` – growth, inflation, monthly central bank decision, unemployment, fiscal/debt, debt crises, FX, nominal GDP, population, stability.
4. `step_events` – exogenous shocks and slow structural drift.
5. Weekly market headlines, daily global history, monthly per-country history.

All rates are annual percentages; everything integrates with `DT = 1/365`. Hazards are annual rates converted to daily probabilities with `1 - exp(-h·DT)`.

### Calibration at t=0

The seed data describe a world where the Ukraine war, sanctions on Russia, etc. are *already* priced in. So at construction the markets are calibrated: oil demand is scaled so that today's supply (net of today's war losses) clears at today's price; wheat and European gas react only to *changes* in breadbasket/supplier losses relative to the start; gold reacts to changes in global risk; each country's debt tolerance is at least 1.3× its starting debt; unrest responds to inflation and unemployment *surprises* relative to slowly adapting reference levels. Without this, the sim "discovers" the Ukraine war on day one and oil triples.

## Macro model (economy.py)

```
growth*   = trend + exo − 0.25·(real rate gap) + oil term + 0.25·(trade-weighted partner gap)
            − 1.5·max(unrest−0.2,0) − war drag − 3·sanctioned share − 4·[debt crisis]
growth    → growth*  with a ~3-month half-life, plus noise

Δinflation = 0.15·gap·4·DT + oil pass-through·(Δln oil)·import dependence
            + food pass-through·(Δln wheat)·food import share + FX pass-through·depreciation
            − anchor·(inflation − target)·DT  [anchor weaker in unstable / autocratic states]
            + monetisation if debt > 90 and stability < 0.45

rate (monthly) = 0.85·rate + 0.15·[compliance·Taylor + (1−compliance)·(neutral + 0.5·inflation)]
Δunemployment  = −0.4·gap·2·DT + reversion to trend
deficit  ← structural + 0.5·(u − u_trend) + war spending + 0.3·interest
Δdebt/GDP = (deficit − debt·nominal growth)·DT
FX depreciation = (π − π_US) − 0.8·(real rate differential) + 6·(risk − 0.3), per year
```

Debt crisis hazard switches on when debt exceeds max(structural threshold, 1.3× start), scaled by the "snowball" (r − π − g). A crisis: FX −20%, inflation +6, stability −0.1, growth −4 for 1–3 years, then a 35% haircut.

## Commodities (commodities.py)

Oil: `supply = Σ prod·(1 − war loss)·(1 − 0.15·sanctioned)·(1 − chokepoints)·(1 − user shock)·capacity`, `demand = Σ cons · demand_level · (P/anchor)^−0.15`, `d ln P = 2.5·(demand − supply)/supply·30·DT − 0.25·ln(P/anchor)·DT + noise`. The anchor drifts toward the price (15%/yr) so structural changes stick; capacity grows 0.8%/yr plus an investment response to price. Gas is analogous with a 0.4 oil link; European gas = hub × starting ratio × (1 + 4·disruption of Europe's suppliers). Wheat reacts to changes in breadbasket war losses, drought, fertilizer (gas-linked), with a self-limiting price response. Copper tracks Chinese and world growth; gold tracks changes in global risk, US real rates and a 3% drift.

## Geopolitics (geopolitics.py)

Tension `T[i,j]` ∈ [0,1], symmetric:

```
dT = 0.5·(base − T)·DT                       reversion to the structural baseline
   + 0.08·sanctions·DT + 0.02·(mil_i + mil_j)·DT·[T>0.3]
   + ally-at-war term (saturating below 0.85) + supporter terms
   − 0.4·trade·(T − 0.1)·DT                  trade dampens
   + 0.05·(neighbour at war)·DT + noise scaled by relevance
```

War hazard per pair per year = `0.08 · logistic((T − 0.82)/0.06)` × 0.25 if both nuclear × 0.4 if both democracies × extended-deterrence shield (0.2 if the target is a close ally of a nuclear power), only for neighbours (< 2500 km) or pairs of large economies. The more autocratic side is the aggressor; the defender's close allies become supporters and democracies sanction the aggressor.

Intensity random-walks with drift from tension and decays with war-weariness; ceasefire hazard = 0.35·(0.3 + damage)·(1.3 − intensity) per year. Wars destroy potential growth, raise military spending, send refugees to neighbours (weighted by distance and stability) and raise their unrest.

Unrest: decays to a structural floor (fragile states and restless democracies stay restless), rises with inflation and unemployment *surprises*, food price rises × import share, economic contraction and war; autocracies suppress visible unrest. Above 0.5: governments fall (democracies, 0.4/yr at max), coups (autocracies, 0.25/yr), civil wars (0.08/yr).

## Events (events.py)

Annual hazards: disasters 1.5 worldwide (allocated by regional exposure × population), drought 0.6, pandemic 0.03, financial crisis 0.06 × (debt and rate stress), tech boom 0.08, cyber-attack 0.5, terror 1.0. Each writes to `exo_growth` and/or state and emits a headline.

## Government "AI" (what exists, what's planned)

Today the agents are rule-based: every government runs a Taylor rule with a compliance level derived from stability and regime; fiscal policy has structural, cyclical and war components; alliances react to wars; democracies sanction aggressors and coup regimes. The roadmap replaces these with explicit per-country agents with personality vectors (hawkishness, fiscal discipline, openness) that choose actions each month, and eventually with learned policies trained against historical outcomes.

## Determinism

`Simulation(seed)` creates one `numpy.random.default_rng(seed)`; every random draw in every module comes from it, in a fixed order. Same seed + same start date + same intervention sequence ⇒ bit-identical world. Keep it that way: never call `np.random.*` or `random.*` directly in engine code.

## Server

`Clock` owns the `Simulation`, runs an asyncio loop at 8 Hz, advances `speed × elapsed` days per frame (bounded to 400 days per frame), and broadcasts `{state, events}` JSON to websocket clients. Interventions and control actions take the clock lock so they never interleave with a step. The engine step runs in a worker thread so the event loop stays responsive.

## Where to plug in

* A new macro relationship: `economy.py`, parameter in `params.MacroParams`, test in `tests/test_engine.py`.
* A new commodity: `commodities.py` (+ price keys in `world.py`, `simulation.PRICE_KEYS`, UI chart).
* A new event type: `events.py`; give it a `type` string, a `severity`, a headline, and a colour in `style.css` (`.feed li.<type>`).
* A new data source: `sync/<source>.py` exposing `fetch(cache, verbose) -> {"countries": {iso: {...}}, "_prices": ..., "_tension": ...}` and a parser test.
* A new map metric: `METRICS` in `app.js` (and the field in `Simulation.snapshot` if it isn't there).
