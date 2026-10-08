"""FastAPI server: runs the simulation in the background and streams state to the UI.

    rws serve            # http://127.0.0.1:8050

REST endpoints under /api, a websocket at /ws that pushes a snapshot + new events
every frame while the clock is running. Time control is in *simulated days per real
second*; the UI exposes presets (1 day/s ... 10 years/s).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..engine.params import Params
from ..engine.simulation import Simulation
from ..engine.world import DATA_DIR
from ..sync import DESCRIPTIONS, SOURCES, cache_status, sync_all

STATIC = Path(__file__).resolve().parent / "static"
SAVE_DIR = Path.cwd() / "saves"
FRAME_HZ = 8  # UI updates per second while running


class Clock:
    """Owns the Simulation and advances it according to `speed` (days / real second)."""

    def __init__(self, seed: int = 42, start: date | None = None, cache_dir: Path | None = None):
        self.cache_dir = cache_dir
        self.reset(seed, start)
        self.running = False
        self.speed = 30.0  # days per second
        self.run_until: int | None = None
        self.lock = asyncio.Lock()
        self.clients: set[WebSocket] = set()
        self._carry = 0.0

    def reset(self, seed: int = 42, start: date | None = None, params: Params | None = None,
              use_live: bool = True) -> None:
        self.sim = Simulation(seed=seed, start=start or date.today(), params=params, cache_dir=self.cache_dir,
                              use_live=use_live)
        self.pending_events: list[dict] = []
        self.running = False
        self.run_until = None
        self._carry = 0.0

    async def loop(self) -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(1 / FRAME_HZ)
            now = time.perf_counter()
            dt, last = now - last, now
            if not self.running:
                continue
            self._carry += self.speed * dt
            days = int(self._carry)
            if self.run_until is not None:
                days = min(days, max(self.run_until - self.sim.day, 0))
            if days <= 0:
                if self.run_until is not None and self.sim.day >= self.run_until:
                    self.running = False
                    self.run_until = None
                    await self.broadcast()
                continue
            self._carry -= days
            days = min(days, 400)  # keep a single frame bounded
            async with self.lock:
                new = await asyncio.to_thread(self.sim.step, days)
            self.pending_events.extend(new)
            if self.run_until is not None and self.sim.day >= self.run_until:
                self.running = False
                self.run_until = None
            await self.broadcast()

    async def broadcast(self) -> None:
        if not self.clients:
            self.pending_events = self.pending_events[-200:]
            return
        msg = json.dumps({"type": "frame", "state": self.sim.snapshot(), "events": self.pending_events[-120:],
                          "running": self.running, "speed": self.speed})
        self.pending_events = []
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


clock = Clock()


class SyncJob:
    """One background sync at a time; progress is polled by the UI."""

    def __init__(self) -> None:
        self.running = False
        self.log: list[dict] = []
        self.started: str | None = None
        self.finished: str | None = None
        self.error: str | None = None

    def start(self, sources: list[str] | None) -> bool:
        if self.running:
            return False
        self.running, self.log, self.error = True, [], None
        self.started, self.finished = datetime.now().isoformat(timespec="seconds"), None

        def progress(source: str, status: str, detail: str) -> None:
            for row in self.log:
                if row["source"] == source:
                    row.update(status=status, detail=detail)
                    break
            else:
                self.log.append({"source": source, "status": status, "detail": detail})

        def work() -> None:
            try:
                sync_all(clock.cache_dir or Path.cwd() / ".rws_cache", sources=sources, progress=progress)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
            finally:
                self.running = False
                self.finished = datetime.now().isoformat(timespec="seconds")

        threading.Thread(target=work, daemon=True).start()
        return True

    def status(self) -> dict[str, Any]:
        return {"running": self.running, "log": self.log, "started": self.started, "finished": self.finished,
                "error": self.error}


sync_job = SyncJob()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(clock.loop())
    yield
    task.cancel()


app = FastAPI(title="RealWorldSim", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------ static
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/geo")
async def geo() -> Response:
    return Response((DATA_DIR / "world.geojson").read_bytes(), media_type="application/geo+json",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/meta")
async def meta() -> dict[str, Any]:
    w = clock.sim.world
    return {
        "countries": [{"iso3": c, "name": w.names[c], "lat": float(w.lat[i]), "lon": float(w.lon[i]),
                       "region": w.region[i], "income_group": w.income_group[i]} for i, c in enumerate(w.iso)],
        "fields": list(w.s.keys()),
        "alliances": w.alliances,
        "chokepoints": {k: v["name"] for k, v in w.chokepoints.items()},
        "shocks": ["recession", "boom", "hyperinflation", "revolution", "default"],
        "params": clock.sim.params.to_dict(),
        "version": app.version,
    }


@app.get("/api/state")
async def state() -> dict[str, Any]:
    return {"state": clock.sim.snapshot(), "running": clock.running, "speed": clock.speed}


@app.get("/api/events")
async def events(limit: int = 200) -> list[dict]:
    return clock.sim.recent_events(limit)


@app.get("/api/history/global")
async def history_global() -> dict[str, Any]:
    return clock.sim.global_history()


@app.get("/api/history/country/{iso}")
async def history_country(iso: str) -> dict[str, Any]:
    iso = iso.upper()
    if iso not in clock.sim.world.index:
        raise HTTPException(404, "unknown country")
    return clock.sim.country_history(iso)


@app.get("/api/country/{iso}")
async def country(iso: str) -> dict[str, Any]:
    iso = iso.upper()
    if iso not in clock.sim.world.index:
        raise HTTPException(404, "unknown country")
    return clock.sim.world.country_snapshot(iso)


@app.get("/api/tension/{iso}")
async def tension_row(iso: str) -> dict[str, Any]:
    iso = iso.upper()
    w = clock.sim.world
    if iso not in w.index:
        raise HTTPException(404, "unknown country")
    return {"iso": w.iso, "tension": [round(float(x), 3) for x in w.tension[w.index[iso]]]}


# ------------------------------------------------------------------ control
class Control(BaseModel):
    action: str                     # play | pause | step | speed | reset | run_to
    speed: float | None = None      # days per second
    days: int | None = None         # for step
    seed: int | None = None         # for reset
    start: str | None = None        # ISO date for reset
    until: str | None = None        # ISO date for run_to
    params: dict | None = None      # for reset


@app.post("/api/control")
async def control(c: Control) -> dict[str, Any]:
    if c.action == "play":
        clock.running = True
    elif c.action == "pause":
        clock.running = False
        clock.run_until = None
    elif c.action == "step":
        async with clock.lock:
            new = await asyncio.to_thread(clock.sim.step, max(1, min(c.days or 1, 3650)))
        clock.pending_events.extend(new)
        await clock.broadcast()
    elif c.action == "speed":
        clock.speed = float(min(max(c.speed or 1.0, 0.1), 36500))
    elif c.action == "reset":
        async with clock.lock:
            params = Params.from_dict(c.params) if c.params else None
            start = date.fromisoformat(c.start) if c.start else None
            clock.reset(seed=c.seed if c.seed is not None else 42, start=start, params=params)
        await clock.broadcast()
    elif c.action == "run_to":
        if not c.until:
            raise HTTPException(400, "until required")
        target = date.fromisoformat(c.until)
        clock.run_until = (target - clock.sim.start).days
        clock.running = clock.run_until > clock.sim.day
    else:
        raise HTTPException(400, f"unknown action {c.action}")
    return {"running": clock.running, "speed": clock.speed, "day": clock.sim.day, "date": clock.sim.today.isoformat()}


class Intervention(BaseModel):
    kind: str
    a: str | None = None
    b: str | None = None
    value: float | None = None
    conflict: str | None = None
    key: str | None = None
    field: str | None = None
    closed: bool | None = None
    alliance: str | None = None
    shock: str | None = None


@app.post("/api/intervene")
async def intervene(iv: Intervention) -> dict[str, Any]:
    sim = clock.sim
    w = sim.world
    for code in (iv.a, iv.b):
        if code and code.upper() not in w.index:
            raise HTTPException(404, f"unknown country {code}")
    a = iv.a.upper() if iv.a else None
    b = iv.b.upper() if iv.b else None
    async with clock.lock:
        try:
            if iv.kind == "set_tension":
                sim.set_tension(a, b, iv.value if iv.value is not None else 0.9)
            elif iv.kind == "declare_war":
                sim.declare_war(a, b, iv.value if iv.value is not None else 0.5)
            elif iv.kind == "ceasefire":
                if not sim.end_conflict(iv.conflict or ""):
                    raise HTTPException(404, "no such active conflict")
            elif iv.kind == "set_intensity":
                sim.set_conflict_intensity(iv.conflict or "", iv.value or 0.5)
            elif iv.kind == "sanction":
                sim.sanction(a, b, iv.value if iv.value is not None else 1.0)
            elif iv.kind == "alliance_sanction":
                sim.alliance_sanction(iv.alliance or "NATO", b or a, iv.value if iv.value is not None else 1.0)
            elif iv.kind == "chokepoint":
                sim.close_chokepoint(iv.key or "hormuz", bool(iv.closed) if iv.closed is not None else True)
            elif iv.kind == "oil_shock":
                sim.oil_supply_shock(iv.value or 0.0)
            elif iv.kind == "set_variable":
                sim.set_variable(a, iv.field or "", iv.value or 0.0)
            elif iv.kind == "shock":
                sim.shock(a, iv.shock or "recession", iv.value if iv.value is not None else 1.0)
            else:
                raise HTTPException(400, f"unknown intervention {iv.kind}")
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
    await clock.broadcast()
    return {"ok": True, "interventions": len(sim.interventions)}


# ------------------------------------------------------------------ data sync
class SyncReq(BaseModel):
    sources: list[str] | None = None


@app.get("/api/data")
async def data_status() -> dict[str, Any]:
    return {
        "cache": cache_status(clock.cache_dir or Path.cwd() / ".rws_cache"),
        "sources": [{"name": k, "description": DESCRIPTIONS[k]} for k in SOURCES],
        "sync": sync_job.status(),
        "world_live_date": clock.sim.world.live_data_date,
    }


@app.post("/api/sync")
async def start_sync(req: SyncReq) -> dict[str, Any]:
    bad = [s for s in (req.sources or []) if s not in SOURCES]
    if bad:
        raise HTTPException(400, f"unknown sources: {bad}")
    if not sync_job.start(req.sources):
        raise HTTPException(409, "a sync is already running")
    return sync_job.status()


class ApplyReq(BaseModel):
    seed: int | None = None


@app.post("/api/apply_live")
async def apply_live(req: ApplyReq) -> dict[str, Any]:
    """Restart the world from the live cache (keeps the current seed unless given)."""
    if sync_job.running:
        raise HTTPException(409, "sync still running")
    async with clock.lock:
        clock.reset(seed=req.seed if req.seed is not None else clock.sim.seed, use_live=True)
    await clock.broadcast()
    return {"ok": True, "live_data_date": clock.sim.world.live_data_date}


class SaveReq(BaseModel):
    name: str = "world"


@app.post("/api/save")
async def save(req: SaveReq) -> dict[str, Any]:
    SAVE_DIR.mkdir(exist_ok=True)
    path = SAVE_DIR / f"{req.name}.rws"
    async with clock.lock:
        clock.sim.save(path)
    return {"ok": True, "path": str(path)}


@app.post("/api/load")
async def load(req: SaveReq) -> dict[str, Any]:
    path = SAVE_DIR / f"{req.name}.rws"
    if not path.exists():
        raise HTTPException(404, "no such save")
    async with clock.lock:
        clock.sim = Simulation.load(path)
        clock.running = False
    await clock.broadcast()
    return {"ok": True}


@app.get("/api/saves")
async def saves() -> list[str]:
    if not SAVE_DIR.exists():
        return []
    return sorted(p.stem for p in SAVE_DIR.glob("*.rws"))


@app.get("/api/export/csv")
async def export_csv() -> Response:
    h = clock.sim.global_history()
    keys = [k for k in h if k != "dates"]
    lines = ["date," + ",".join(keys)]
    for i, d in enumerate(h["dates"]):
        lines.append(d + "," + ",".join(str(h[k][i]) for k in keys))
    return Response("\n".join(lines), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=realworldsim_global.csv"})


# ------------------------------------------------------------------ websocket
@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    clock.clients.add(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "frame", "state": clock.sim.snapshot(),
                                              "events": clock.sim.recent_events(80),
                                              "running": clock.running, "speed": clock.speed}))
        while True:
            await websocket.receive_text()  # keep-alive / ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        clock.clients.discard(websocket)


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def run(host: str = "127.0.0.1", port: int = 8050, seed: int = 42, start: str | None = None,
        cache_dir: str | None = None, open_browser: bool = False, auto_sync_days: float | None = None) -> None:
    import uvicorn

    clock.cache_dir = Path(cache_dir) if cache_dir else None
    if auto_sync_days is not None:
        st = cache_status(clock.cache_dir or Path.cwd() / ".rws_cache")
        if not st.get("exists") or st.get("age_days", 1e9) > auto_sync_days:
            print(f"live data cache missing or older than {auto_sync_days} days - syncing in the background")
            sync_job.start(None)
    clock.reset(seed=seed, start=date.fromisoformat(start) if start else None)
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
