"""Fake-HA mit steuerbarem Band: reagiert auf call_service wie die PitPat-Integration."""
import asyncio
import json
import time

from aiohttp import web

E = "sensor.walkingpad_"
LOG = []


class Pad:
    def __init__(self):
        self.state, self.speed, self.target = "stopped", 0.0, 0.0
        self.dist, self.dur = 0.041, 0
        self.subs = []

    async def emit(self, key, val):
        for ws, sid in list(self.subs):
            try:
                await ws.send_json({"id": sid, "type": "event", "event": {"c": {
                    E + key: {"+": {"s": str(val), "lc": time.time()}}}}})
            except Exception:
                pass

    async def set_state(self, s):
        self.state = s
        await self.emit("state", s)

    async def loop(self):
        acc = 0.0
        while True:
            await asyncio.sleep(0.5)
            old = self.speed
            if self.state == "running":
                if abs(self.target - self.speed) > 0.05:
                    self.speed = round(self.speed + max(-0.3, min(0.3, self.target - self.speed)), 1)
                self.dist += self.speed * 0.5 / 3600
                acc += 0.5
                if acc >= 1:
                    acc = 0
                    self.dur += 1
                    await self.emit("duration", self.dur)
                    await self.emit("distance", f"{self.dist:.3f}")
            elif self.speed > 0:
                self.speed = max(0.0, round(self.speed - 0.4, 1))
            if self.speed != old:
                await self.emit("speed", self.speed)

    async def service(self, domain, service, entity, data):
        LOG.append((domain, service, entity, data))
        print("SERVICE", domain, service, entity, data, "| state:", self.state, flush=True)
        if entity == "button.walkingpad_start":
            await self.set_state("countdown")
            await asyncio.sleep(1.5)
            self.dist, self.dur, self.target, self.speed = 0.0, 0, 2.0, 1.0
            await self.emit("distance", 0.0)
            await self.set_state("running")
            await self.emit("speed", 1.0)
        elif entity == "button.walkingpad_pause_resume":
            if self.state == "running":
                self.target = 0
                await self.set_state("paused")
            elif self.state == "paused":
                self.target = 2.0
                await self.set_state("running")
        elif entity == "button.walkingpad_stop":
            self.target = 0
            await self.set_state("stopped")
        elif entity == "number.walkingpad_speed":
            self.target = float(data["value"])
        else:
            return False
        return True


pad = Pad()


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"type": "auth_required"})
    await ws.receive_json()
    await ws.send_json({"type": "auth_ok"})
    async for raw in ws:
        m = json.loads(raw.data)
        if m["type"] == "subscribe_entities":
            await ws.send_json({"id": m["id"], "type": "result", "success": True})
            now = time.time()
            init = {E + k: {"s": str(v), "a": {}, "lc": now} for k, v in
                    (("state", pad.state), ("speed", pad.speed), ("distance", pad.dist),
                     ("duration", pad.dur), ("calories", 0), ("steps", 0))}
            await ws.send_json({"id": m["id"], "type": "event", "event": {"a": init}})
            pad.subs.append((ws, m["id"]))
        elif m["type"] == "call_service":
            ok = await pad.service(m["domain"], m["service"], m["target"]["entity_id"], m["service_data"])
            await ws.send_json({"id": m["id"], "type": "result", "success": ok,
                                **({} if ok else {"error": {"code": "not_found", "message": "Entity not found"}})})
    return ws


async def main():
    app = web.Application()
    app.router.add_get("/api/websocket", ws_handler)
    r = web.AppRunner(app)
    await r.setup()
    await web.TCPSite(r, "127.0.0.1", 18123).start()
    await pad.loop()

asyncio.run(main())
