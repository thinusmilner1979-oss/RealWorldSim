"""Command-line entry point: `rws`."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


def cmd_serve(a: argparse.Namespace) -> None:
    from .server.app import run

    print(f"RealWorldSim  http://{a.host}:{a.port}   (seed {a.seed})")
    run(host=a.host, port=a.port, seed=a.seed, start=a.start, cache_dir=a.cache, open_browser=not a.no_browser)


def cmd_run(a: argparse.Namespace) -> None:
    """Headless run: print a yearly summary and notable events."""
    from .engine.simulation import Simulation

    sim = Simulation(seed=a.seed, start=date.fromisoformat(a.start) if a.start else None,
                     cache_dir=Path(a.cache) if a.cache else None)
    notable = {"war_start", "ceasefire", "coup", "civil_war", "pandemic", "financial_crisis",
               "chokepoint_closed", "government_falls", "debt_crisis"}
    for _ in range(a.years):
        events = sim.step(365)
        w = sim.world
        print(f"{sim.today}  gdp ${w.world_gdp()/1000:.1f}T  growth {sim.history.daily['world_growth'][-1]:.1f}%  "
              f"infl {sim.history.daily['world_inflation'][-1]:.1f}%  oil ${w.prices['oil']:.0f}  "
              f"wheat ${w.prices['wheat']:.1f}  gold ${w.prices['gold']:.0f}  wars {len(w.active_conflicts())}  "
              f"risk {w.global_risk():.2f}")
        if a.verbose:
            for e in events:
                if e["type"] in notable:
                    print(f"    {e['date']}  {e['text']}")
    if a.save:
        sim.save(a.save)
        print("saved", a.save)


def cmd_sync(a: argparse.Namespace) -> None:
    if a.history:
        from .backtest.history import fetch_history

        for year in a.history:
            out = fetch_history(year, Path(a.cache), verbose=True)
            print(f"wrote {out}")
        return
    from .sync import sync_all

    out = sync_all(Path(a.cache), sources=a.sources, verbose=True)
    print(f"wrote {out}")


def cmd_backtest(a: argparse.Namespace) -> None:
    from .backtest import run_backtest

    run_backtest(start=a.start, end=a.end, runs=a.runs, workers=a.workers,
                 cache=Path(a.cache) if a.cache else None, out_dir=Path(a.out))


def cmd_seed(a: argparse.Namespace) -> None:
    import runpy

    tools = Path(__file__).resolve().parents[1] / "tools" / "build_seed.py"
    sys.argv = [str(tools)] + ([a.file] if a.file else [])
    runpy.run_path(str(tools), run_name="__main__")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="rws", description="RealWorldSim - an open-source world model")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8050)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--start", help="simulation start date (ISO), default today")
    s.add_argument("--cache", default=".rws_cache", help="directory holding live-sync data")
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    r = sub.add_parser("run", help="headless run, yearly summary to stdout")
    r.add_argument("--years", type=int, default=10)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--start")
    r.add_argument("--cache", default=".rws_cache")
    r.add_argument("--save", help="save the final world to this file")
    r.add_argument("-v", "--verbose", action="store_true", help="print notable events")
    r.set_defaults(fn=cmd_run)

    y = sub.add_parser("sync", help="pull live data from free public sources into the cache")
    y.add_argument("--cache", default=".rws_cache")
    y.add_argument("--sources", nargs="*", default=None,
                   help="subset of: worldbank ucdp gdelt fred (default: all)")
    y.add_argument("--history", nargs="*", type=int, metavar="YEAR",
                   help="instead of today's data, fetch World Bank values for these years (for backtests)")
    y.set_defaults(fn=cmd_sync)

    b = sub.add_parser("backtest", help="start in the past, run an ensemble, score it against what happened")
    b.add_argument("--start", default="2015-01-01", help="scenario start date (a bundled data/history/<year>.json)")
    b.add_argument("--end", default="2025-01-01")
    b.add_argument("--runs", type=int, default=20, help="ensemble size (seeds 0..runs-1)")
    b.add_argument("--workers", type=int, default=None, help="parallel processes (default: all cores)")
    b.add_argument("--cache", default=".rws_cache", help="where `rws sync --history` put sourced values")
    b.add_argument("--out", default="backtests", help="directory for JSON reports")
    b.set_defaults(fn=cmd_backtest)

    d = sub.add_parser("seed", help="rebuild bundled seed data from Natural Earth")
    d.add_argument("file", nargs="?", help="local ne_50m_admin_0_countries.geojson (else download)")
    d.set_defaults(fn=cmd_seed)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
