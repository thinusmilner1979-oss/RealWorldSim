"""Backtesting: start the world in the past, run an ensemble, score it against history.

    rws backtest --start 2015-01-01 --end 2025-01-01 --runs 50

The score is the project's compass. Every change to the model should move it, and
`backtests/` keeps the JSON reports so progress is visible.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from ..engine.params import Params
from .history import load_scenario, load_scorecard
from .runner import run_ensemble
from .scoring import score


def run_backtest(start: str = "2015-01-01", end: str = "2025-01-01", runs: int = 20, workers: int | None = None,
                 cache: Path | None = None, params: Params | None = None, out_dir: Path | None = None,
                 scorecard_name: str = "scorecard_2015_2025", verbose: bool = True) -> dict:
    year = date.fromisoformat(start).year
    scenario = load_scenario(year, cache)
    scorecard = load_scorecard(scorecard_name)
    t0 = time.time()

    def progress(done: int, total: int) -> None:
        if verbose:
            print(f"\r  runs {done}/{total}  ({time.time() - t0:.0f}s)", end="", flush=True)

    ensemble = run_ensemble(scenario, start, end, runs=runs, workers=workers, params=params, progress=progress)
    if verbose:
        print()
    result = score(ensemble, scorecard)
    result["meta"] = {"start": start, "end": end, "runs": runs, "seconds": round(time.time() - t0, 1),
                      "scenario_synced": scenario.get("_synced"), "params": (params or Params()).to_dict()}
    out_dir = Path(out_dir or "backtests")
    out_dir.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    path = out_dir / f"backtest_{year}_{runs}runs_{stamp}.json"
    path.write_text(json.dumps(result, indent=1))
    result["meta"]["path"] = str(path)
    if verbose:
        print(format_report(result))
    return result


def format_report(result: dict) -> str:
    s = result["summary"]
    lines = [
        "",
        f"=== Backtest {result['meta']['start']} -> {result['meta']['end']}  ({s['runs']} runs, "
        f"{result['meta']['seconds']}s) ===",
        f"composite score        {s['composite']}   (1 = perfect)",
        f"series coverage        {s['series_coverage']}   (share of actual values inside the 10-90% band; aim ~0.8)",
        f"event Brier            {s['event_brier']}   (0 = every real event foreseen in its window)",
        f"wars per run           {s['wars_per_run']}   (actual: {result['false_alarms']['interstate_wars_actual']})",
        f"war on peaceful pair   {s['war_on_peaceful_pair']}   (false-alarm rate; aim ~0)",
        f"coup in stable democracy {s['coup_in_stable_democracy']}",
        "",
        "-- series (median vs actual) --",
    ]
    for name, v in result["series"].items():
        lines.append(f"{name:<16} coverage {v['coverage']:<5} mae {v['mae']:<7} band {v['band_width']}")
        lines.append("   " + "  ".join(f"{r['year']}:{r['actual']:g}/{r['median']:g}" for r in v["rows"]))
    lines.append("")
    lines.append("-- events (p within window / p ever) --")
    for r in sorted(result["events"]["rows"], key=lambda r: -r["p_window"]):
        lines.append(f"{r['p_window']:.2f} / {r['p_ever']:.2f}  {r['desc']}")
    lines.append("")
    fa = result["false_alarms"]
    worst = sorted(fa["war_on_peaceful_pair"].items(), key=lambda kv: -kv[1])[:4]
    lines.append("-- false alarms --  " + ", ".join(f"{k} {v:.2f}" for k, v in worst))
    lines.append(f"report: {result['meta'].get('path')}")
    return "\n".join(lines)
