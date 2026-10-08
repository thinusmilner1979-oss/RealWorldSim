"""World Bank Indicators API (free, no key): https://api.worldbank.org/v2/"""
from __future__ import annotations

from pathlib import Path

from .http import get_json

BASE = "https://api.worldbank.org/v2/country/all/indicator/{ind}?format=json&mrv=1&per_page=500"

INDICATORS = {
    "NY.GDP.MKTP.CD": ("gdp_usd_bn", lambda v: v / 1e9),
    "SP.POP.TOTL": ("population", float),
    "NY.GDP.MKTP.KD.ZG": ("growth", float),
    "FP.CPI.TOTL.ZG": ("inflation", float),
    "SL.UEM.TOTL.ZS": ("unemployment", float),
    "GC.DOD.TOTL.GD.ZS": ("debt_gdp", float),
    "MS.MIL.XPND.GD.ZS": ("mil_spend_gdp", float),
    "FR.INR.LEND": ("lending_rate", float),
}

# World Bank aggregates (regions, income groups) share the same endpoint; skip them.
AGGREGATE_PREFIXES = ("1", "4", "7", "8", "B8", "EAR", "EAS", "ECA", "ECS", "EMU", "EUU", "FCS", "HIC", "HPC",
                      "IBD", "IBT", "IDA", "IDB", "IDX", "INX", "LAC", "LCN", "LDC", "LIC", "LMC", "LMY", "LTE",
                      "MEA", "MIC", "MNA", "NAC", "OED", "OSS", "PRE", "PSS", "PST", "SAS", "SSA", "SSF", "SST",
                      "TEA", "TEC", "TLA", "TMN", "TSA", "TSS", "UMC", "WLD", "ARB", "CEB", "CSS", "AFE", "AFW")


def parse(payload: list, field: str, conv) -> dict[str, dict]:
    """Turn a World Bank JSON page into {iso3: {field: value, field_year: year}}."""
    out: dict[str, dict] = {}
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        return out
    for row in payload[1]:
        iso = row.get("countryiso3code") or ""
        if len(iso) != 3 or iso in AGGREGATE_PREFIXES or row.get("value") is None:
            continue
        try:
            out[iso] = {field: conv(row["value"]), f"{field}_year": int(row["date"])}
        except (TypeError, ValueError):
            continue
    return out


def fetch(cache: Path, verbose: bool = False) -> dict:
    countries: dict[str, dict] = {}
    for ind, (field, conv) in INDICATORS.items():
        try:
            payload = get_json(BASE.format(ind=ind))
        except Exception as e:  # noqa: BLE001
            print(f"  worldbank {ind}: {e}")
            continue
        got = parse(payload, field, conv)
        for iso, vals in got.items():
            countries.setdefault(iso, {}).update(vals)
        if verbose:
            print(f"  {ind:<20} {field:<14} {len(got)} countries")
    # World Bank has no policy-rate series; approximate from inflation if the lending rate is missing.
    for v in countries.values():
        if "lending_rate" in v and "policy_rate" not in v:
            v["policy_rate"] = max(0.0, v["lending_rate"] - 2.5)
    return {"countries": countries} if countries else {}
