"""Parser tests on canned responses (the network is not touched)."""
from realworldsim.sync import fred, gdelt, ucdp, worldbank


def test_worldbank_parse_skips_aggregates_and_nulls():
    payload = [{"page": 1}, [
        {"countryiso3code": "ZAF", "date": "2024", "value": 4.0e11},
        {"countryiso3code": "WLD", "date": "2024", "value": 1.0e14},
        {"countryiso3code": "FRA", "date": "2024", "value": None},
        {"countryiso3code": "", "date": "2024", "value": 1.0},
    ]]
    got = worldbank.parse(payload, "gdp_usd_bn", lambda v: v / 1e9)
    assert got == {"ZAF": {"gdp_usd_bn": 400.0, "gdp_usd_bn_year": 2024}}


def test_fred_latest_value_skips_missing():
    text = "DATE,DCOILBRENTEU\n2025-09-29,67.1\n2025-09-30,.\n"
    assert fred.latest_value(text) == 67.1
    assert fred.latest_value("DATE,X\n") is None


def test_ucdp_aggregate_and_intensity():
    events = [{"country": "Ukraine", "best": 5000}, {"country": "Ukraine", "best": 7000},
              {"country": "Sudan", "best": 300}, {"country": "Narnia", "best": 10}]
    got = ucdp.aggregate(events)
    assert got["UKR"]["battle_deaths_12m"] == 12000
    assert 0.5 < got["UKR"]["war_intensity_live"] < 0.7
    assert got["SDN"]["war_intensity_live"] > 0.2
    assert "Narnia" not in got
    assert ucdp.intensity_from_deaths(0) == 0.0
    assert ucdp.intensity_from_deaths(1e7) == 1.0


def _row(a1, a2, root, gold, mentions=5):
    r = [""] * 61
    r[gdelt.COL_A1], r[gdelt.COL_A2], r[gdelt.COL_ROOT] = a1, a2, root
    r[gdelt.COL_GOLD], r[gdelt.COL_MENT] = str(gold), str(mentions)
    return r


def test_gdelt_parse_rows():
    rows = [_row("FRA", "", "14", -6.5)] * 10 + [_row("FRA", "", "04", 1.0)] * 20 \
        + [_row("ISR", "IRN", "19", -10)] * 15 + [_row("ISR", "IRN", "04", 2)] * 15 + [_row("USA", "CHN", "11", -7)] * 3
    countries, tension = gdelt.parse_rows(rows)
    assert countries["FRA"]["unrest_live"] > countries["USA"]["unrest_live"] if "USA" in countries else True
    assert countries["ISR"]["gdelt_conflict_share"] == 0.5
    assert "IRN-ISR" in tension and tension["IRN-ISR"] == 0.3
