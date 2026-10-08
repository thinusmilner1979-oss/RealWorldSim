"""GDELT 2.0 event stream (free, no key): http://data.gdeltproject.org/gdeltv2/

We read the most recent few 15-minute export files (world news events coded with
CAMEO), then count, per country, protest events (root code 14) and conflict events
(root codes 18-20) relative to all events -> an unrest index; and, per country pair,
hostile events (Goldstein scale < -5) -> tension bumps.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from .http import get, get_text

MASTER = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
N_FILES = 8  # last 2 hours of global events (~50k events)

# column indexes in the GDELT 2.0 events export
COL_A1 = 7     # Actor1CountryCode (ISO3)
COL_A2 = 17    # Actor2CountryCode
COL_ROOT = 28  # EventRootCode
COL_GOLD = 30  # GoldsteinScale
COL_MENT = 33  # NumMentions


def parse_rows(rows) -> tuple[dict[str, dict], dict[str, float]]:
    totals: dict[str, float] = {}
    protest: dict[str, float] = {}
    conflict: dict[str, float] = {}
    pairs: dict[str, float] = {}
    for r in rows:
        if len(r) < 40:
            continue
        a1, a2, root = r[COL_A1], r[COL_A2], r[COL_ROOT]
        try:
            w = float(r[COL_MENT] or 1)
            gold = float(r[COL_GOLD] or 0)
        except ValueError:
            continue
        for actor in (a1, a2):
            if len(actor) != 3:
                continue
            totals[actor] = totals.get(actor, 0) + w
            if root == "14":
                protest[actor] = protest.get(actor, 0) + w
            elif root in ("18", "19", "20"):
                conflict[actor] = conflict.get(actor, 0) + w
        if len(a1) == 3 and len(a2) == 3 and a1 != a2 and gold < -5:
            key = "-".join(sorted((a1, a2)))
            pairs[key] = pairs.get(key, 0) + w * (-gold / 10)
    countries = {}
    for iso, tot in totals.items():
        if tot < 20:
            continue
        p = protest.get(iso, 0) / tot
        c = conflict.get(iso, 0) / tot
        # typical shares: protest ~2-4%, conflict ~5-10%; map to 0..1 with a soft ceiling
        unrest = min(1.0, p * 8 + c * 2)
        countries[iso] = {"gdelt_protest_share": round(p, 4), "gdelt_conflict_share": round(c, 4),
                          "unrest_live": round(unrest, 3), "gdelt_events": int(tot)}
    # normalise pairwise hostility to 0..0.3 bumps
    if pairs:
        mx = max(pairs.values())
        tension = {k: round(0.3 * v / mx, 3) for k, v in pairs.items() if v / mx > 0.05}
    else:
        tension = {}
    return countries, tension


def fetch(cache: Path, verbose: bool = False) -> dict:
    master = get_text(MASTER, timeout=120)
    urls = [line.split()[-1] for line in master.strip().splitlines() if line.endswith(".export.CSV.zip")]
    urls = urls[-N_FILES:]
    rows: list[list[str]] = []
    for u in urls:
        try:
            z = zipfile.ZipFile(io.BytesIO(get(u, timeout=120)))
            for name in z.namelist():
                text = z.read(name).decode("utf-8", errors="replace")
                rows.extend(csv.reader(io.StringIO(text), delimiter="\t"))
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  gdelt {u}: {e}")
    if not rows:
        return {}
    countries, tension = parse_rows(rows)
    if verbose:
        top = sorted(countries.items(), key=lambda kv: -kv[1]["unrest_live"])[:8]
        print(f"  {len(rows)} events; most restless:", ", ".join(f"{k} {v['unrest_live']}" for k, v in top))
    return {"countries": countries, "_tension": tension}
