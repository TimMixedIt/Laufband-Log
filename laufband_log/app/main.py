"""Laufband-Log: speichert Walking-Pad-Workouts aus Home Assistant."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

from ha_client import HAClient
from recorder import Recorder

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("laufband")

STATIC = Path(__file__).parent / "static"
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

DEFAULTS = {
    "state_entity": "sensor.walkingpad_state",
    "speed_entity": "sensor.walkingpad_speed",
    "distance_entity": "sensor.walkingpad_distance",
    "duration_entity": "sensor.walkingpad_duration",
    "calories_entity": "sensor.walkingpad_calories",
    "steps_entity": "sensor.walkingpad_steps",
    "min_duration_seconds": 60,
    "max_pause_minutes": 30,
    "max_disconnect_minutes": 10,
    "start_button": "button.walkingpad_start",
    "pause_button": "button.walkingpad_pause_resume",
    "stop_button": "button.walkingpad_stop",
    "speed_number": "number.walkingpad_speed",
    "max_control_speed": 6.0,
}


def load_options() -> dict:
    opts = dict(DEFAULTS)
    p = DATA_DIR / "options.json"
    if p.exists():
        opts.update({k: v for k, v in json.loads(p.read_text()).items() if v not in (None, "")})
    return opts


def supervisor_token() -> str | None:
    tok = os.environ.get("SUPERVISOR_TOKEN")
    if tok:
        return tok
    f = Path("/run/s6/container_environment/SUPERVISOR_TOKEN")
    return f.read_text().strip() if f.exists() else None


INGRESS_IPS = {"172.30.32.2", "127.0.0.1", "::1"}


def make_app(rec: Recorder, ha: HAClient | None, ingress_only: bool,
             opts: dict | None = None) -> web.Application:
    opts = opts or DEFAULTS
    @web.middleware
    async def guard(request, handler):
        if ingress_only and request.remote not in INGRESS_IPS:
            return web.Response(status=403, text="Nur über Home Assistant erreichbar.")
        resp = await handler(request)
        if request.path.startswith("/api/") or request.path == "/":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app = web.Application(middlewares=[guard])

    async def index(_):
        return web.FileResponse(STATIC / "index.html")

    async def live(_):
        out = rec.live()
        out["ha_connected"] = bool(ha and ha.connected)
        out["ha_error"] = ha.last_error if ha else None
        out["now"] = time.time()
        out["max_control_speed"] = float(opts["max_control_speed"])
        return web.json_response(out)

    async def control(request):
        body = await request.json()
        action = body.get("action")
        state = (rec.values.get("state") or "").lower()
        try:
            if action == "start":
                if state not in ("stopped", "paused"):
                    raise web.HTTPConflict(text="Starten geht nur, wenn das Band steht.")
                if state == "paused":   # Fortsetzen läuft über Pause/Weiter
                    await ha.call_service("button", "press", opts["pause_button"])
                else:
                    await ha.call_service("button", "press", opts["start_button"])
            elif action == "pause":
                if state not in ("running", "paused"):
                    raise web.HTTPConflict(text="Das Band läuft nicht.")
                await ha.call_service("button", "press", opts["pause_button"])
            elif action == "stop":
                await ha.call_service("button", "press", opts["stop_button"])
            elif action == "speed":
                if state != "running":
                    raise web.HTTPConflict(text="Tempo lässt sich nur bei laufendem Band ändern.")
                v = round(min(float(opts["max_control_speed"]),
                              max(0.5, float(body.get("value")))), 1)
                await ha.call_service("number", "set_value", opts["speed_number"], {"value": v})
            else:
                raise web.HTTPBadRequest(text="Unbekannte Aktion")
        except RuntimeError as e:
            raise web.HTTPBadGateway(text=f"Home Assistant: {e}")
        log.info("Steuerung: %s %s", action, body.get("value", ""))
        return web.json_response({"ok": True})

    async def workouts(_):
        return web.json_response(rec.list_workouts())

    async def workout(request):
        w = rec.get_workout(int(request.match_info["wid"]))
        if not w:
            raise web.HTTPNotFound(text="Workout nicht gefunden")
        return web.json_response(w)

    async def delete(request):
        wid = int(request.match_info["wid"])
        if rec.active and rec.active.id == wid:
            raise web.HTTPConflict(text="Laufendes Workout kann nicht gelöscht werden")
        rec.delete(wid)
        return web.json_response({"ok": True})

    async def export_csv(request):
        wid = int(request.match_info["wid"])
        w = rec.get_workout(wid, max_points=10**9)
        if not w:
            raise web.HTTPNotFound()
        buf = io.StringIO()
        cw = csv.writer(buf, delimiter=";")
        cw.writerow(["zeit", "sekunden_seit_start", "tempo_kmh", "strecke_km",
                     "aktive_zeit_s", "kcal", "schritte"])
        for t, sp, d, du, c, st in rec.raw_samples(wid):
            cw.writerow([datetime.fromtimestamp(t).isoformat(timespec="seconds"),
                         f"{t - w['started_at']:.1f}",
                         "" if sp is None else f"{sp:.2f}".replace(".", ","),
                         "" if d is None else f"{d:.3f}".replace(".", ","),
                         "" if du is None else f"{du:.0f}",
                         "" if c is None else f"{c:.0f}",
                         "" if st is None else f"{st:.0f}"])
        name = datetime.fromtimestamp(w["started_at"]).strftime("laufband_%Y-%m-%d_%H%M.csv")
        return web.Response(text=buf.getvalue(), content_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def no_icon(_):
        return web.Response(status=204)

    app.router.add_get("/", index)
    app.router.add_get("/favicon.ico", no_icon)
    app.router.add_get("/api/live", live)
    app.router.add_post("/api/control", control)
    app.router.add_get("/api/workouts", workouts)
    app.router.add_get("/api/workouts/{wid:\\d+}", workout)
    app.router.add_delete("/api/workouts/{wid:\\d+}", delete)
    app.router.add_get("/api/workouts/{wid:\\d+}/csv", export_csv)
    app.router.add_static("/static/", STATIC)
    return app


async def main():
    opts = load_options()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rec = Recorder(str(DATA_DIR / "workouts.db"),
                   min_duration_s=float(opts["min_duration_seconds"]),
                   max_pause_s=float(opts["max_pause_minutes"]) * 60,
                   max_lost_s=float(opts["max_disconnect_minutes"]) * 60)

    entity_map = {opts[f"{k}_entity"]: k for k in
                  ("state", "speed", "distance", "duration", "calories", "steps")
                  if opts.get(f"{k}_entity")}

    tok = supervisor_token()
    if tok:
        ws_url, token, ingress_only = "ws://supervisor/core/websocket", tok, True
    else:
        base = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
        ws_url = base.replace("http", "ws", 1) + "/api/websocket"
        token, ingress_only = os.environ.get("HA_TOKEN", ""), False

    ha = HAClient(ws_url, token, entity_map, rec.feed)

    async def ticker():
        while True:
            try:
                rec.tick()
            except Exception:  # noqa: BLE001
                log.exception("Fehler im Takt")
            await asyncio.sleep(1)

    app = make_app(rec, ha, ingress_only, opts)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    port = int(os.environ.get("PORT", "8099"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Laufband-Log läuft auf Port %s, beobachte %s", port, ", ".join(entity_map))
    await asyncio.gather(ha.run(), ticker())


if __name__ == "__main__":
    asyncio.run(main())
