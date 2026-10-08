# Backtesting

The backtest is the project's compass. It answers the only question that matters for a
model like this: *given the world as it was, how much probability did the model put on
what actually happened?*

```bash
rws backtest                                  # 2015 -> 2025, 20 runs, all cores
rws backtest --runs 100 --workers 8           # tighter bands, ~10 min on 8 cores
rws sync --history 2015 && rws backtest       # sourced World Bank 2015 figures instead of the bundled ones
```

Each run writes `backtests/backtest_<year>_<runs>runs_<date>.json` and prints a report.

## How it works

1. **Start state** – `realworldsim/data/history/2015.json`: the world on 1 Jan 2015 from the
   public record (GDP, inflation, rates, debt for ~100 economies; the conflicts active then –
   Donbas, Syria, ISIS, Yemen, Libya, Boko Haram…; $55 oil, $1,200 gold; pre-JCPOA Iran
   sanctions, post-Crimea Russia sanctions). `rws sync --history 2015` overlays sourced
   World Bank values. Regime, stability and alliances are today's – a known simplification.
2. **Ensemble** – N seeds run from the start to the end date in parallel. Nothing from the
   live cache is used.
3. **Scorecard** – `scorecard_2015_2025.json`: yearly world growth, inflation, Brent, gold,
   wheat and active-war counts; growth/inflation paths for a few countries; 29 dated events
   (Covid, the 2022 invasion, Gaza, the Sahel coups, Sudan, Tigray, the Sri Lanka / Lebanon /
   Zambia / Ghana / Argentina defaults, Brexit, Assad's fall…); and *non-events* (pairs that
   stayed at peace, democracies that stayed stable, the real number of interstate wars).
4. **Scores**
   * **series coverage** – share of actual yearly values inside the ensemble's 10–90% band.
     A calibrated model scores ≈0.8; lower means over-confident, higher means vague.
   * **mae** – error of the ensemble median.
   * **event Brier** – mean of (1 − p)² where p is the share of runs with a matching event
     within ±window years of the real date (0 = perfect, 1 = never). `p_ever` is also shown.
   * **false alarms** – wars per run vs. the real 4; share of runs with war on a pair that
     stayed at peace; coups/civil wars in stable democracies.
   * **composite** – mean of coverage, (1 − Brier) and (1 − false-alarm rate). One number to
     argue about, not a scientific claim.

A simmering conflict going full-scale (`war_escalation`, intensity crossing 0.6) counts as a
war starting, so the Donbas → 2022 path can score.

## Baseline

8-run backtests on the day the harness was added (October 2026), before and after the first
tuning pass it prompted (base-rate hazards for coups, defaults and government collapses;
slower ceasefires; wider oil noise; escalation events):

| | before | after |
|---|---|---|
| composite | 0.445 | **0.53** |
| series coverage | 0.35 | 0.47 |
| event Brier | 0.969 | 0.815 |
| wars per run (actual 4) | 0.9 | 1.5 |
| war on peaceful pair | 0.05 | 0.06 |
| P(2022 invasion, ±2y / ever) | 0.12 / 0.12 | 0.62 / 0.88 |
| P(Covid-scale pandemic) | 0.12 | 0.25–0.5 |
| P(Mali coup) | 0 | 0.5 |

What the harness says is still wrong, in order of size:

1. **No 2022 inflation spike, no 2020 crash.** World inflation sits at ~2.5% whatever happens;
   the model has no pandemic-stimulus / supply-chain mechanism and the pandemic hit is too
   small. Growth coverage 0.6 is carried by the calm years.
2. **Oil is too calm.** Band ±$6 vs. a real range of $42–101. The 2014–16 glut and the 2022
   spike are both outside it. Needs OPEC behaviour and a demand-shock channel.
3. **Specific wars are unforeseeable** (Gaza 2023, Israel–Iran 2024, Tigray, Sudan 2023 all at
   0). Some of that is irreducible; some is missing mechanism (internal power struggles in
   autocracies; insurgent groups as actors).
4. **Defaults** are rare and land on the wrong countries. Needs reserves, external debt and
   the IMF.
5. **Wars still too few** (1.5 vs 4) and the ones that happen are on the wrong pairs
   (Korea is the standing false alarm).

Every item is a GitHub issue. If your change moves the composite up *without* raising the
false-alarm rate, it's an improvement; paste the before/after table in the PR.

## Caveats

* Ten years is one draw of a very noisy process. A perfect model would not score 1.0 – many
  real events were low-probability. Use the score to compare model versions, not as a claim
  about the world.
* The scorecard and the 2015 state are hand-written from the public record and approximate.
  Corrections welcome – with a source.
* The bundled yearly figures are world aggregates; country-level scoring covers only the
  handful of countries in `country_series`.
