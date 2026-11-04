"""Websocket-Verbindung zu Home Assistant (subscribe_entities)."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp

log = logging.getLogger("laufband.ha")

DIST_TO_KM = {"km": 1.0, "m": 0.001, "mi": 1.609344, "ft": 0.0003048}
SPEED_TO_KMH = {"km/h": 1.0, "mph": 1.609344, "m/s": 3.6}


class HAClient:
    def __init__(self, ws_url: str, token: str, entity_map: dict[str, str], on_updates):
        """entity_map: entity_id -> key (state/speed/distance/...)"""
        self.ws_url = ws_url
        self.token = token
        self.entity_map = entity_map
        self.on_updates = on_updates
        self.connected = False
        self.last_error: str | None = None
        self._units: dict[str, str] = {}
        self._states: dict[str, str] = {}
        self._ws = None
        self._next_id = 100
        self._pending: dict[int, asyncio.Future] = {}

    async def call_service(self, domain: str, service: str, entity_id: str,
                           data: dict | None = None, timeout: float = 8.0):
        """Dienst in HA aufrufen; wirft RuntimeError bei Fehler."""
        if not self._ws or not self.connected:
            raise RuntimeError("Keine Verbindung zu Home Assistant")
        self._next_id += 1
        mid = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send_json({"id": mid, "type": "call_service", "domain": domain,
                                  "service": service, "service_data": data or {},
                                  "target": {"entity_id": entity_id}})
        try:
            res = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)
        if not res.get("success"):
            err = res.get("error") or {}
            raise RuntimeError(err.get("message") or str(err))
        return res

    async def run(self):
        backoff = 2
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    await self._session(session)
                    backoff = 2
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"{type(e).__name__}: {e}"
                    log.warning("Verbindung zu Home Assistant: %s", self.last_error)
                self.connected = False
                self._ws = None
                for f in self._pending.values():
                    if not f.done():
                        f.set_result({"success": False, "error": {"message": "Verbindung getrennt"}})
                # Verbindung weg -> für die Workout-Logik wie "Band getrennt"
                self.on_updates([("state", None, time.time())])
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _session(self, session: aiohttp.ClientSession):
        async with session.ws_connect(self.ws_url, heartbeat=30, max_msg_size=0) as ws:
            msg = await ws.receive_json(timeout=15)
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Unerwartete Begrüßung: {msg}")
            await ws.send_json({"type": "auth", "access_token": self.token})
            msg = await ws.receive_json(timeout=15)
            if msg.get("type") != "auth_ok":
                raise RuntimeError(f"Anmeldung abgelehnt: {msg.get('message', msg)}")
            await ws.send_json({"id": 1, "type": "subscribe_entities",
                                "entity_ids": list(self.entity_map)})
            self._ws = ws
            self.connected = True
            self.last_error = None
            log.info("Mit Home Assistant verbunden, %d Entitäten abonniert",
                     len(self.entity_map))
            async for raw in ws:
                if raw.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(raw.data)
                    for m in data if isinstance(data, list) else [data]:
                        self._handle(m)
                elif raw.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    break
            raise RuntimeError("Websocket geschlossen")

    def _handle(self, m: dict):
        fut = self._pending.get(m.get("id")) if m.get("type") == "result" else None
        if fut is not None:
            if not fut.done():
                fut.set_result(m)
            return
        if m.get("type") == "result" and not m.get("success", True):
            log.error("Abo fehlgeschlagen: %s", m.get("error"))
            self.last_error = str(m.get("error"))
            return
        if m.get("type") != "event":
            return
        ev = m.get("event") or {}
        now = time.time()
        updates = []
        for eid, st in (ev.get("a") or {}).items():
            attrs = st.get("a") or {}
            if "unit_of_measurement" in attrs:
                self._units[eid] = attrs["unit_of_measurement"]
            ts = st.get("lu") or st.get("lc") or now
            self._states[eid] = st.get("s")
            updates.append(self._convert(eid, st.get("s"), ts))
        for eid, diff in (ev.get("c") or {}).items():
            plus = diff.get("+") or {}
            attrs = plus.get("a") or {}
            if "unit_of_measurement" in attrs:
                self._units[eid] = attrs["unit_of_measurement"]
            if "s" not in plus:
                continue
            ts = plus.get("lc") or plus.get("lu") or now
            self._states[eid] = plus["s"]
            updates.append(self._convert(eid, plus["s"], ts))
        for eid in ev.get("r") or []:
            updates.append(self._convert(eid, None, now))
        updates = [u for u in updates if u]
        if updates:
            self.on_updates(updates)

    def _convert(self, eid, raw, ts):
        key = self.entity_map.get(eid)
        if not key:
            return None
        ts = float(ts)
        if key == "state":
            if raw in (None, "unavailable", "unknown"):
                return ("state", "disconnected", ts)
            return ("state", str(raw).lower(), ts)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return (key, None, ts)
        unit = (self._units.get(eid) or "").strip()
        if key == "distance":
            v *= DIST_TO_KM.get(unit, 1.0)
        elif key == "speed":
            v *= SPEED_TO_KMH.get(unit, 1.0)
        elif key == "duration":
            v *= {"min": 60.0, "h": 3600.0}.get(unit, 1.0)
        return (key, v, ts)
