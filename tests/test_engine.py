"""Engine tests: construction, determinism, stability over a long run, interventions."""
from datetime import date

import numpy as np
import pytest

from realworldsim.engine.simulation import Simulation
from realworldsim.engine.world import World


def test_world_has_every_country():
    w = World()
    assert w.n >= 190
    for code in ("USA", "CHN", "ZAF", "UKR", "TWN", "XKX", "PSE"):
        assert code in w.index
    assert abs(w.tension - w.tension.T).max() < 1e-9
    assert w.s["gdp"].min() > 0 and w.s["population"].min() > 0


def test_determinism():
    a = Simulation(seed=7, start=date(2026, 1, 1))
    b = Simulation(seed=7, start=date(2026, 1, 1))
    a.step(200)
    b.step(200)
    assert a.world.prices == b.world.prices
    assert np.array_equal(a.world.s["gdp"], b.world.s["gdp"])
    assert [c.id for c in a.world.conflicts] == [c.id for c in b.world.conflicts]
    c = Simulation(seed=8, start=date(2026, 1, 1))
    c.step(200)
    assert c.world.prices != a.world.prices


@pytest.mark.parametrize("seed", [1, 2])
def test_long_run_stays_sane(seed):
    sim = Simulation(seed=seed, start=date(2026, 1, 1))
    for _ in range(20):
        sim.step(365)
        s = sim.world.s
        assert np.isfinite(s["gdp"]).all() and np.isfinite(s["inflation"]).all()
        assert 10 < sim.world.prices["oil"] < 500
        assert 1 < sim.world.prices["wheat"] < 40
        w = sim.gdp = sim.world.gdp_weights()
        world_growth = float((s["growth"] * w).sum())
        assert -12 < world_growth < 10
        assert float((s["inflation"] * w).sum()) < 25
        assert (s["unrest"] > 0.5).sum() < 60  # the whole world never riots at once
    assert sim.world.world_gdp() > 1.2 * Simulation(seed=seed, start=date(2026, 1, 1)).world.world_gdp()


def test_interventions_have_effects():
    sim = Simulation(seed=3, start=date(2026, 1, 1))
    sim.step(30)
    oil0 = sim.world.prices["oil"]
    sim.close_chokepoint("hormuz")
    sim.step(60)
    assert sim.world.prices["oil"] > oil0 * 1.2
    sim.close_chokepoint("hormuz", closed=False)

    before = len(sim.world.active_conflicts())
    c = sim.declare_war("CHN", "TWN", 0.6)
    assert len(sim.world.active_conflicts()) == before + 1
    sim.step(30)
    twn = sim.world.i("TWN")
    assert sim.world.s["war_intensity"][twn] > 0.3
    assert sim.end_conflict(c.id)
    assert len(sim.world.active_conflicts()) == before

    sim.set_tension("USA", "CAN", 0.95)
    assert sim.world.tension[sim.world.i("USA"), sim.world.i("CAN")] == pytest.approx(0.95)
    sim.sanction("USA", "ZAF", 1.0)
    assert sim.world.s["sanctioned_share"][sim.world.i("ZAF")] > 0
    with pytest.raises(KeyError):
        sim.set_variable("ZAF", "nonsense", 1)


def test_snapshot_and_history_shapes():
    sim = Simulation(seed=5, start=date(2026, 1, 1))
    sim.step(70)
    snap = sim.snapshot()
    assert snap["day"] == 70 and len(snap["iso"]) == sim.world.n
    assert len(snap["fields"]["growth"]) == sim.world.n
    assert len(snap["hotspots"]) == 12
    gh = sim.global_history()
    assert len(gh["dates"]) == 71 == len(gh["oil"])
    ch = sim.country_history("ZAF")
    assert len(ch["dates"]) == len(ch["gdp"]) >= 3


def test_save_load_roundtrip(tmp_path):
    sim = Simulation(seed=9, start=date(2026, 1, 1))
    sim.step(40)
    p = tmp_path / "w.rws"
    sim.save(p)
    sim2 = Simulation.load(p)
    sim.step(10)
    sim2.step(10)
    assert sim.world.prices == sim2.world.prices
