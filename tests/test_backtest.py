"""Backtest harness: scenario loading, scoring on synthetic ensembles, a tiny real run."""
from datetime import date

from realworldsim.backtest import run_backtest
from realworldsim.backtest.history import available_scenarios, load_scenario, load_scorecard
from realworldsim.backtest.runner import run_one, yearly_mean
from realworldsim.backtest.scoring import score, score_events, score_series
from realworldsim.engine.simulation import Simulation


def test_scenario_and_scorecard_load():
    assert 2015 in available_scenarios()
    sc = load_scenario(2015)
    assert sc["countries"]["USA"]["gdp_usd_bn"] < 20000
    assert any(c["id"] == "donbas" for c in sc["active_conflicts"])
    card = load_scorecard()
    assert "2020" in card["series"]["world_growth"] and len(card["events"]) > 20


def test_world_starts_in_2015_state():
    sim = Simulation(seed=1, start=date(2015, 1, 1), scenario=load_scenario(2015), use_live=False)
    w = sim.world
    assert w.prices["oil"] == 55.0
    assert abs(w.s["gdp"][w.i("USA")] - 18200) < 1
    assert w.s["sanctioned_share"][w.i("RUS")] < w.s["sanctioned_share"][w.i("IRN")]
    assert any(c.id == "syria" for c in w.active_conflicts())
    assert not any(c.id == "ukraine" for c in w.active_conflicts())  # 2022 war must not pre-exist


def test_yearly_mean():
    assert yearly_mean(["2015-01-01", "2015-06-01", "2016-01-01"], [1, 3, 10]) == {"2015": 2.0, "2016": 10.0}


def _fake_runs():
    return [
        {"seed": 0, "series": {"oil": {"2015": 50, "2016": 60}}, "country_series": {},
         "events": [{"type": "war_start", "country": "RUS", "country2": "UKR", "date": "2021-06-01"},
                    {"type": "coup", "country": "MLI", "date": "2020-01-01"}]},
        {"seed": 1, "series": {"oil": {"2015": 70, "2016": 40}}, "country_series": {},
         "events": [{"type": "war_escalation", "country": "UKR", "country2": "RUS", "date": "2018-01-01"},
                    {"type": "pandemic", "country": None, "date": "2019-05-01"}]},
    ]


def test_score_series_and_events():
    runs = _fake_runs()
    s = score_series(runs, {"oil": {"2015": 55, "2016": 100}})
    assert s["oil"]["coverage"] == 0.5 and s["oil"]["rows"][0]["actual"] == 55
    ev = score_events(runs, [
        {"id": "u", "desc": "", "type": "war_start", "a": "RUS", "b": "UKR", "date": "2022-02-24", "window": 2},
        {"id": "m", "desc": "", "type": "coup", "country": "MLI", "date": "2020-08-18", "window": 2},
        {"id": "c", "desc": "", "type": "pandemic", "date": "2020-03-11", "window": 3},
        {"id": "x", "desc": "", "type": "coup", "country": "FRA", "date": "2020-01-01", "window": 2},
    ])
    rows = {r["id"]: r for r in ev["rows"]}
    assert rows["u"]["p_ever"] == 1.0 and rows["u"]["p_window"] == 0.5  # escalation counts; one in window
    assert rows["m"]["p_window"] == 0.5 and rows["c"]["p_window"] == 0.5 and rows["x"]["p_window"] == 0.0
    full = score(runs, {"series": {"oil": {"2015": 55}}, "events": [], "non_events": {
        "pairs_at_peace": [["RUS", "UKR"], ["CHN", "TWN"]], "stable_democracies": ["FRA"]}})
    assert full["false_alarms"]["war_on_peaceful_pair"]["RUS-UKR"] == 0.5
    assert full["summary"]["composite"] is not None


def test_run_one_short():
    sc = load_scenario(2015)
    r = run_one((3, sc, "2015-01-01", "2015-04-01", None, ("USA",)))
    assert "2015" in r["series"]["oil"] and "USA" in r["country_series"]
    assert r["final"]["world_gdp"] > 0


def test_run_backtest_end_to_end(tmp_path):
    res = run_backtest(start="2015-01-01", end="2015-07-01", runs=2, workers=1, out_dir=tmp_path, verbose=False)
    assert res["summary"]["runs"] == 2 and (tmp_path / res["meta"]["path"].split("/")[-1]).exists()
