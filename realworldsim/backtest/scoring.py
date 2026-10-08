"""Score an ensemble against the scorecard of what actually happened.

Series:  for each year, the ensemble's 10-90% band and median vs. the actual value.
         coverage = share of years inside the band (a calibrated model: ~0.8);
         mae = mean absolute error of the median; width = mean band width (sharpness).
Events:  p_window = share of runs with a matching event within +/- window years of the
         real date; p_ever = share with one anywhere in the period. Brier = (1 - p_window)^2
         averaged over events (0 perfect, 1 hopeless). A base-rate-free "skill" number is
         not attempted: the scorecard is too small for that to mean much.
False alarms: wars per run vs. the real count; wars on pairs that stayed at peace; coups
         and civil wars in stable democracies.
"""
from __future__ import annotations

from datetime import date

import numpy as np


def _band(values: list[float]) -> tuple[float, float, float]:
    a = np.asarray(values, dtype=float)
    return float(np.percentile(a, 10)), float(np.median(a)), float(np.percentile(a, 90))


def score_series(runs: list[dict], actual: dict[str, dict[str, float]], key: str = "series") -> dict:
    out = {}
    for name, truth in actual.items():
        years = sorted(truth)
        rows, inside, errs, widths = [], 0, [], []
        for y in years:
            vals = [r[key][name][y] for r in runs if name in r[key] and y in r[key][name]]
            if not vals:
                continue
            lo, med, hi = _band(vals)
            t = truth[y]
            rows.append({"year": y, "actual": t, "p10": round(lo, 2), "median": round(med, 2), "p90": round(hi, 2)})
            inside += int(lo <= t <= hi)
            errs.append(abs(med - t))
            widths.append(hi - lo)
        if rows:
            out[name] = {"coverage": round(inside / len(rows), 3), "mae": round(float(np.mean(errs)), 3),
                         "band_width": round(float(np.mean(widths)), 3), "rows": rows}
    return out


def score_country_series(runs: list[dict], actual: dict[str, dict[str, dict[str, float]]]) -> dict:
    out = {}
    for iso, fields in actual.items():
        flat_runs = [{"series": r["country_series"].get(iso, {})} for r in runs if iso in r["country_series"]]
        if flat_runs:
            out[iso] = score_series(flat_runs, fields)
    return out


def _matches(ev: dict, spec: dict) -> bool:
    if spec["type"] == "war_start":
        # a simmering conflict going full-scale counts as the war "starting" (Donbas -> 2022)
        if ev["type"] not in ("war_start", "war_escalation"):
            return False
        return {ev.get("country"), ev.get("country2")} == {spec["a"], spec["b"]}
    if ev["type"] != spec["type"]:
        return False
    if "country" in spec and spec["type"] not in ("pandemic", "chokepoint_closed", "financial_crisis"):
        return ev.get("country") == spec["country"]
    return True


def score_events(runs: list[dict], events: list[dict]) -> dict:
    rows = []
    for spec in events:
        d = date.fromisoformat(spec["date"])
        w = spec.get("window", 2)
        in_window = ever = 0
        for r in runs:
            hits = [e for e in r["events"] if _matches(e, spec)]
            if hits:
                ever += 1
                if any(abs((date.fromisoformat(e["date"]) - d).days) <= w * 365 for e in hits):
                    in_window += 1
        n = max(len(runs), 1)
        p_w, p_e = in_window / n, ever / n
        rows.append({"id": spec["id"], "desc": spec["desc"], "date": spec["date"], "type": spec["type"],
                     "p_window": round(p_w, 3), "p_ever": round(p_e, 3), "brier": round((1 - p_w) ** 2, 3)})
    brier = float(np.mean([r["brier"] for r in rows])) if rows else None
    by_type: dict[str, list[float]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r["p_window"])
    return {"brier": round(brier, 3) if brier is not None else None,
            "mean_p_window": round(float(np.mean([r["p_window"] for r in rows])), 3) if rows else None,
            "mean_p_ever": round(float(np.mean([r["p_ever"] for r in rows])), 3) if rows else None,
            "by_type": {k: round(float(np.mean(v)), 3) for k, v in by_type.items()}, "rows": rows}


def score_false_alarms(runs: list[dict], non_events: dict) -> dict:
    n = max(len(runs), 1)
    wars = [sum(1 for e in r["events"] if e["type"] == "war_start") for r in runs]
    peace_pairs = {}
    for a, b in non_events.get("pairs_at_peace", []):
        k = sum(1 for r in runs if any(e["type"] == "war_start" and {e["country"], e["country2"]} == {a, b}
                                       for e in r["events"]))
        peace_pairs[f"{a}-{b}"] = round(k / n, 3)
    dem = {}
    for iso in non_events.get("stable_democracies", []):
        k = sum(1 for r in runs if any(e["type"] in ("coup", "civil_war") and e["country"] == iso for e in r["events"]))
        dem[iso] = round(k / n, 3)
    return {"interstate_wars_per_run": round(float(np.mean(wars)), 2), "interstate_wars_actual":
            non_events.get("interstate_wars_total"), "war_on_peaceful_pair": peace_pairs,
            "mean_war_on_peaceful_pair": round(float(np.mean(list(peace_pairs.values()))), 3) if peace_pairs else None,
            "coup_or_civil_war_in_stable_democracy": dem,
            "mean_coup_in_stable_democracy": round(float(np.mean(list(dem.values()))), 3) if dem else None}


def score(runs: list[dict], scorecard: dict) -> dict:
    series = score_series(runs, scorecard["series"])
    countries = score_country_series(runs, scorecard.get("country_series", {}))
    events = score_events(runs, scorecard["events"])
    false_alarms = score_false_alarms(runs, scorecard.get("non_events", {}))
    cov = [v["coverage"] for v in series.values()]
    summary = {
        "runs": len(runs),
        "series_coverage": round(float(np.mean(cov)), 3) if cov else None,
        "event_brier": events["brier"],
        "event_mean_p_window": events["mean_p_window"],
        "wars_per_run": false_alarms["interstate_wars_per_run"],
        "war_on_peaceful_pair": false_alarms["mean_war_on_peaceful_pair"],
        "coup_in_stable_democracy": false_alarms["mean_coup_in_stable_democracy"],
    }
    # one number to argue about: average of (coverage, 1 - brier, 1 - false alarm rate)
    parts = [summary["series_coverage"], 1 - (summary["event_brier"] or 1),
             1 - (summary["war_on_peaceful_pair"] or 0)]
    summary["composite"] = round(float(np.mean([p for p in parts if p is not None])), 3)
    return {"summary": summary, "series": series, "countries": countries, "events": events,
            "false_alarms": false_alarms}
