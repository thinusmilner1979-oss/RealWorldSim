# Contributing

Thanks for looking. RealWorldSim is early, ambitious and deliberately open-ended; most of the interesting work has not been done yet.

## Ground rules

* **The engine stays deterministic.** All randomness comes from the simulation's single `numpy.random.Generator`. Never use `np.random.*` or `random.*` directly.
* **Keep it stable.** `tests/test_engine.py::test_long_run_stays_sane` runs 20 years on two seeds and asserts the world doesn't explode. If your change makes it fail, tune, don't delete the test.
* **Constants go in `engine/params.py`**, not inline. Every number should be nameable, documented and tunable.
* **Calibrate changes, don't just add them.** The world at t=0 should look like today's world; new mechanisms must not "discover" existing conditions and react to them (see *Calibration at t=0* in `docs/ARCHITECTURE.md`).
* **Free data only.** No source that costs money or requires a paid key. Free registration is acceptable only if the data is redistributable.
* Keep PRs focused. One mechanism, one data source, one UI feature.

## Getting set up

```bash
git clone https://github.com/thinusmilner1979-oss/RealWorldSim.git
cd RealWorldSim
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q             # ~90 s; the long-run test dominates
ruff check .
rws serve             # UI at http://127.0.0.1:8765
```

Quick feedback loop while tuning: `rws run --years 10 --seed 1 -v`.

## What we need most

See `ROADMAP.md`. In short:

1. **Backtesting** — initialise the world at a past date from historical data and score the ensemble against what actually happened. This is the project's compass.
2. **Government agents** — per-country decision making with personalities.
3. **Ensembles** — run many seeds, show distributions instead of one path.
4. **Better data** — IMF WEO, EIA, SIPRI, BIS policy rates, trade matrices (UN Comtrade), OWID energy.
5. **Economics review** — if you know macro, the equations in `economy.py` want your eyes.
6. **UI** — ensemble views, scenario comparison, timeline scrubbing, better mobile layout.

## Reporting implausible behaviour

The most useful bug report is: *seed X, by year Y, Z happens and it shouldn't.* Include the `rws run -v` output. "Oil hits $400 after a Hormuz closure" is a calibration issue worth fixing; "Belgium invades Luxembourg" is a logic bug.

## Code style

Python 3.11+, type hints, `ruff` clean, docstrings that explain the *model*, not the syntax. Front-end is vanilla JS on purpose: no build step, no framework, so anyone can edit it.
