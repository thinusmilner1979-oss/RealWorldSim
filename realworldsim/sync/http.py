"""Tiny HTTP helper (stdlib only, no requests dependency)."""
from __future__ import annotations

import gzip
import json
import urllib.request
from typing import Any

UA = "RealWorldSim/0.1 (+https://github.com/thinusmilner1979-oss/RealWorldSim)"


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


def get_json(url: str, timeout: int = 60) -> Any:
    return json.loads(get(url, timeout).decode("utf-8"))


def get_text(url: str, timeout: int = 60) -> str:
    return get(url, timeout).decode("utf-8", errors="replace")
