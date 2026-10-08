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


def test_owid_parse_latest_year():
    from realworldsim.sync import owid
    text = ("Entity,Code,Year,value\nSouth Africa,ZAF,2020,1.0\nSouth Africa,ZAF,2022,2.0\n"
            "World,OWID_WRL,2022,9\nAfrica,,2022,3\n")
    got = owid.parse(text, float)
    assert got == {"ZAF": (2.0, 2022)}


def test_climate_drought_index():
    from datetime import date, timedelta

    from realworldsim.sync import climate
    end = date(2026, 9, 30)
    days = 365 * 3
    dates = [(end - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    # 2 mm/day normally, but only 0.5 mm/day in the last 90 days -> drought index ~0.75
    rain = [2.0] * (days - 90) + [0.5] * 90
    temp = [20.0] * (days - 90) + [22.0] * 90
    r = climate.drought_index(dates, rain, temp)
    assert 0.7 < r["drought_index"] < 0.8 and abs(r["temp_anomaly_c"] - 2.0) < 0.05
    assert climate.drought_index(dates[:50], rain[:50], temp[:50]) == {}
    oni = climate.parse_oni(" SEAS  YR  TOTAL ANOM\n JJA 2026 27.5 0.7\n")
    assert oni == {"oni": 0.7, "season": "JJA", "year": 2026, "state": "el_nino"}


def test_unhcr_aggregate_and_stooq_parse():
    from realworldsim.sync import stooq, unhcr
    items = [{"coo_iso": "SYR", "coa_iso": "TUR", "refugees": "3000000", "asylum_seekers": "0"},
             {"coo_iso": "SYR", "coa_iso": "DEU", "refugees": "500000", "asylum_seekers": "100000"}]
    got = unhcr.aggregate(items)
    assert got["SYR"]["refugees_out_live"] == 3600000 and got["TUR"]["refugees_in_live"] == 3000000
    csv_text = "Symbol,Date,Time,Open,High,Low,Close,Volume\nXAUUSD,2026-10-07,22:00:00,1,2,0,3610.5,0\n"
    assert stooq.parse(csv_text) == 3610.5


def test_portwatch_disruption():
    import time
    from datetime import date, timedelta

    from realworldsim.sync import portwatch
    today = date(2026, 10, 8)
    feats = []
    for k in range(200):
        d = today - timedelta(days=k)
        n = 20 if k <= 30 else 60  # traffic down to a third in the last month
        ts_ms = int(time.mktime(d.timetuple())) * 1000
        feats.append({"attributes": {"portname": "Bab el-Mandeb Strait", "date": ts_ms, "n_total": n}})
    out = portwatch.disruption(feats, today)
    assert 0.6 < out["bab_el_mandeb"]["disruption"] < 0.7
