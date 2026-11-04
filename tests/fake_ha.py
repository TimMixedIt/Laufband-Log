"""Mini-Home-Assistant: auth + subscribe_entities im komprimierten HA-Format."""
import asyncio
import json
import time

from aiohttp import web

TOKEN = "test-token"
E = "sensor.walkingpad_"


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"type": "auth_required", "ha_version": "2026.11.0"})
    msg = await ws.receive_json()
    if msg.get("access_token") != TOKEN:
        await ws.send_json({"type": "auth_invalid", "message": "Invalid access token"})
        await ws.close()
        return ws
    await ws.send_json({"type": "auth_ok", "ha_version": "2026.11.0"})
    sub = await ws.receive_json()
    assert sub["type"] == "subscribe_entities", sub
    print("abonniert:", sub["entity_ids"], flush=True)
    sid = sub["id"]
    await ws.send_json({"id": sid, "type": "result", "success": True, "result": None})
    now = time.time()
    init = {
        E + "state": {"s": "stopped", "a": {"device_class": "enum"}, "c": "x", "lc": now - 3600},
        E + "speed": {"s": "0.0", "a": {"unit_of_measurement": "km/h"}, "c": "x", "lc": now - 3600},
        E + "distance": {"s": "0.041", "a": {"unit_of_measurement": "km"}, "c": "x", "lc": now - 3600},
        E + "duration": {"s": "0", "a": {"unit_of_measurement": "s"}, "c": "x", "lc": now - 3600},
        E + "calories": {"s": "0", "a": {"unit_of_measurement": "kcal"}, "c": "x", "lc": now - 3600},
        E + "steps": {"s": "0", "a": {}, "c": "x", "lc": now - 3600},
    }
    await ws.send_json({"id": sid, "type": "event", "event": {"a": init}})

    async def change(eid, s):
        await ws.send_json({"id": sid, "type": "event",
                            "event": {"c": {E + eid: {"+": {"s": str(s), "lc": time.time(), "c": "y"}}}}})

    async def attr_only(eid):  # Diff ohne Zustandsänderung (nur lu) – muss ignoriert werden
        await ws.send_json({"id": sid, "type": "event",
                            "event": {"c": {E + eid: {"+": {"lu": time.time(), "c": "z"}}}}})

    await asyncio.sleep(0.5)
    await change("state", "countdown")
    await change("distance", "0.0")
    await asyncio.sleep(1)
    await change("state", "running")
    dist, dur, speed = 0.0, 0, 1.0
    import os
    n = int(os.environ.get("FAKE_STEPS", "14"))
    kcal = 0.0
    for i in range(n):
        tgt = 4.2 if i < 30 else (3.6 if i < 55 else 4.6)
        speed = min(tgt, speed + 0.8) if speed < tgt else max(tgt, speed - 0.4)
        await change("speed", f"{speed:.1f}")
        await asyncio.sleep(0.5)
        dur += 1
        dist += speed / 3600 * 1.0
        await change("duration", dur)
        await change("distance", f"{dist:.3f}")
        await attr_only("speed")
        kcal += 0.35
        if i % 3 == 0:
            await change("calories", int(kcal))
        await asyncio.sleep(0.5)
    await change("state", "stopped")
    for s in (3.5, 2.0, 0.5, 0.0):
        await change("speed", s)
        await asyncio.sleep(0.3)
    await asyncio.sleep(1)
    await change("duration", 0)
    print("Szenario fertig", flush=True)
    async for _ in ws:
        pass
    return ws


app = web.Application()
app.router.add_get("/api/websocket", ws_handler)
web.run_app(app, port=18123, print=None)
