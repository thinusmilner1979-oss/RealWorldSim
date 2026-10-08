"""IMF PortWatch chokepoint transit counts (open ArcGIS feature service, no key).

Daily vessel transits through Hormuz, Bab el-Mandeb, Suez, Malacca, Taiwan Strait, Bosporus
and others. We compare the last 30 days with the previous 12 months to detect disruption
(e.g. the Red Sea after late 2023).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .http import get_json

BASE = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/"
        "FeatureServer/0/query?where=date>%3DDATE'{start}'&outFields=portname,date,n_total&f=json"
        "&resultRecordCount=20000&orderByFields=date")

NAME_MAP = {
    "Strait of Hormuz": "hormuz", "Bab el-Mandeb Strait": "bab_el_mandeb", "Suez Canal": "suez",
    "Malacca Strait": "malacca", "Taiwan Strait": "taiwan_strait", "Bosporus Strait": "bosporus",
    "Bab el-Mandeb": "bab_el_mandeb", "Strait of Malacca": "malacca",
}


def _guess_key(name: str) -> str | None:
    n = name.lower()
    for word, key in (("hormuz", "hormuz"), ("mandeb", "bab_el_mandeb"), ("suez", "suez"), ("malacca", "malacca"),
                      ("taiwan", "taiwan_strait"), ("bosporus", "bosporus"), ("bosphorus", "bosporus")):
        if word in n:
            return key
    return None


def disruption(features: list[dict], today: date | None = None) -> dict[str, dict]:
    today = today or date.today()
    recent: dict[str, list[float]] = {}
    base: dict[str, list[float]] = {}
    for f in features:
        a = f.get("attributes", {})
        key = NAME_MAP.get(a.get("portname", "")) or _guess_key(str(a.get("portname", "")))
        if not key or a.get("n_total") is None or a.get("date") is None:
            continue
        raw = a["date"]
        try:
            if isinstance(raw, str):
                d = date.fromisoformat(raw[:10])
            else:
                d = date.fromtimestamp(raw / 1000.0 if raw > 1e11 else raw)
        except (ValueError, OSError, TypeError):
            continue
        (recent if (today - d).days <= 30 else base).setdefault(key, []).append(float(a["n_total"]))
    out = {}
    for key, vals in recent.items():
        b = base.get(key)
        if not b or not vals:
            continue
        ratio = (sum(vals) / len(vals)) / max(sum(b) / len(b), 1e-9)
        out[key] = {"transits_per_day": round(sum(vals) / len(vals), 1), "normal_per_day": round(sum(b) / len(b), 1),
                    "disruption": round(max(0.0, min(1.0, 1 - ratio)), 3)}
    return out


def fetch(cache: Path, verbose: bool = False) -> dict:
    start = (date.today() - timedelta(days=400)).isoformat()
    payload = get_json(BASE.format(start=start), timeout=120)
    feats = payload.get("features", [])
    if not feats:
        if verbose:
            print(f"  no features; response keys: {list(payload)[:6]} {str(payload)[:200]}")
        return {}
    out = disruption(feats)
    if verbose:
        names = sorted({str(f.get("attributes", {}).get("portname")) for f in feats})
        print(f"  {len(feats)} rows; chokepoint names in feed: {', '.join(names)[:300]}")
        sample = feats[0].get("attributes", {})
        print(f"  sample row: {str(sample)[:200]}")
        if out:
            print("  " + ", ".join(f"{k} {v['disruption']:.0%}" for k, v in out.items()))
    return {"_chokepoints": out} if out else {}
