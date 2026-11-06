"""Workout-Erkennung und Speicherung.

Reine Logik ohne Netzwerk: bekommt Messwerte mit Zeitstempel (feed) und
regelmäßige Takte (tick) und schreibt Workouts + Messpunkte in SQLite.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field

log = logging.getLogger("laufband.recorder")

COUNTERS = ("distance", "duration", "calories", "steps")
NUMERIC = ("speed",) + COUNTERS

RUNNING = "running"
PAUSED = "paused"
LOST = "lost"        # Verbindung zum Band weg, Workout noch offen
ENDING = "ending"    # "stopped" gemeldet, Band rollt aus, kurz warten

HEARTBEAT_S = 5.0     # Messpunkt alle 5 s, auch wenn sich nichts ändert
MIN_GAP_S = 1.0       # Zählerupdates höchstens 1x pro Sekunde speichern
STOP_GRACE_S = 8.0    # nach "stopped" noch Ausrollen + letzte Zähler mitnehmen
FLUSH_S = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    status        TEXT NOT NULL,            -- active | done
    started_at    REAL NOT NULL,
    ended_at      REAL,
    duration_s    REAL DEFAULT 0,
    distance_km   REAL DEFAULT 0,
    calories      REAL DEFAULT 0,
    steps         REAL DEFAULT 0,
    avg_speed     REAL DEFAULT 0,
    max_speed     REAL DEFAULT 0,
    pause_s       REAL DEFAULT 0,
    pause_count   INTEGER DEFAULT 0,
    intervals     TEXT DEFAULT '[]',        -- [{"s":..,"e":..,"kind":"pause"|"lost"}]
    spark         TEXT DEFAULT '[]',
    state_json    TEXT DEFAULT '{}',        -- interner Zustand für Neustarts
    end_reason    TEXT,
    person        TEXT                      -- wer gelaufen ist
);
CREATE TABLE IF NOT EXISTS samples (
    workout_id INTEGER NOT NULL,
    t          REAL NOT NULL,
    speed      REAL,
    distance   REAL,
    duration   REAL,
    calories   REAL,
    steps      REAL
);
CREATE INDEX IF NOT EXISTS idx_samples_w ON samples(workout_id, t);
"""


@dataclass
class Counter:
    """Zähler des Bandes, robust gegen Resets.

    Das Band setzt Zeit/Kalorien nach Stopp auf 0, die Strecke erst beim
    nächsten Start. Ein Rückgang ohne vorherigen Anstieg = alter Wert wurde
    genullt (kein Fortschritt verloren). Ein Rückgang nach Anstieg = echter
    Reset mitten im Training (z. B. nach Verbindungsabbruch) -> aufaddieren.
    """
    acc: float = 0.0
    seg_start: float | None = None
    last_raw: float | None = None
    increased: bool = False

    def total(self) -> float:
        if self.last_raw is None or self.seg_start is None:
            return self.acc
        return self.acc + max(0.0, self.last_raw - self.seg_start)

    def feed(self, raw: float, ending: bool) -> bool:
        """Gibt True zurück, wenn der Gesamtwert gestiegen ist."""
        before = self.total()
        if self.last_raw is None:
            self.seg_start = raw
            self.last_raw = raw
        elif raw >= self.last_raw:
            if raw > self.last_raw:
                self.increased = True
            self.last_raw = raw
        elif ending:
            pass  # Reset nach dem Stopp ignorieren
        elif not self.increased:
            self.seg_start = 0.0
            self.last_raw = raw
        else:
            self.acc = self.total()
            self.seg_start = 0.0
            self.last_raw = raw
            self.increased = False
        return self.total() > before + 1e-9

    def to_dict(self):
        return {"acc": self.acc, "seg_start": self.seg_start,
                "last_raw": self.last_raw, "increased": self.increased}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class Workout:
    id: int
    started_at: float
    phase: str = RUNNING
    counters: dict = field(default_factory=lambda: {k: Counter() for k in COUNTERS})
    intervals: list = field(default_factory=list)   # offene + geschlossene Pausen/Lücken
    phase_since: float = 0.0
    stop_at: float | None = None
    last_progress_t: float = 0.0
    last_sample_t: float = 0.0
    last_speed: float | None = None
    max_speed: float = 0.0
    buffer: list = field(default_factory=list)
    last_flush: float = 0.0

    def totals(self) -> dict:
        return {k: self.counters[k].total() for k in COUNTERS}

    def open_interval(self, kind, t):
        self.close_interval(t)
        self.intervals.append({"s": t, "e": None, "kind": kind})

    def close_interval(self, t):
        if self.intervals and self.intervals[-1]["e"] is None:
            self.intervals[-1]["e"] = max(t, self.intervals[-1]["s"])

    def state_dict(self):
        return {
            "phase": self.phase, "phase_since": self.phase_since,
            "counters": {k: c.to_dict() for k, c in self.counters.items()},
            "intervals": self.intervals, "last_progress_t": self.last_progress_t,
            "last_sample_t": self.last_sample_t, "last_speed": self.last_speed,
            "max_speed": self.max_speed,
        }


class Recorder:
    def __init__(self, db_path: str, min_duration_s: float = 60,
                 max_pause_s: float = 1800, max_lost_s: float = 600):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(workouts)")}
        if "person" not in cols:   # Datenbanken vor 1.3.0
            self.db.execute("ALTER TABLE workouts ADD COLUMN person TEXT")
        self.db.commit()
        self.min_duration_s = min_duration_s
        self.max_pause_s = max_pause_s
        self.max_lost_s = max_lost_s
        self.values: dict = {"state": None, **{k: None for k in NUMERIC}}
        self.values_t: float | None = None
        self.active: Workout | None = None
        self._recover()

    # ------------------------------------------------------------------ input
    def feed(self, updates: list[tuple[str, object, float]]):
        """updates: Liste von (key, wert, zeitstempel). Zustand zuerst."""
        updates = sorted(updates, key=lambda u: 0 if u[0] == "state" else 1)
        for key, value, t in updates:
            self.values_t = t
            if key == "state":
                self.values["state"] = value
                self._on_state(value, t)
                continue
            if value is None:          # unavailable/unknown -> ignorieren
                continue
            self.values[key] = value
            w = self.active
            if not w:
                continue
            if key == "speed":
                self._sample(t, speed_changed=(value != w.last_speed))
                w.last_speed = value
                if w.phase != ENDING:
                    w.max_speed = max(w.max_speed, value)
            else:
                if w.counters[key].feed(float(value), ending=(w.phase == ENDING)):
                    w.last_progress_t = t
                self._sample(t, speed_changed=False)

    def tick(self, now: float | None = None):
        now = time.time() if now is None else now
        w = self.active
        if not w:
            return
        if w.phase == ENDING and w.stop_at is not None and now - w.stop_at >= STOP_GRACE_S:
            self._finalize(w.stop_at, "stopped")
            return
        if w.phase == PAUSED and now - w.phase_since >= self.max_pause_s:
            self._finalize(w.phase_since, "pause_timeout")
            return
        if w.phase == LOST and now - w.phase_since >= self.max_lost_s:
            self._finalize(max(w.last_progress_t, w.phase_since - 1), "connection_lost")
            return
        if w.phase in (RUNNING, PAUSED) and now - w.last_sample_t >= HEARTBEAT_S:
            self._sample(now, speed_changed=False, force=True)
        if now - w.last_flush >= FLUSH_S:
            self._flush(now)

    # ------------------------------------------------------------- state logic
    def _on_state(self, state, t):
        w = self.active
        st = (state or "").lower()
        if st == "running":
            if w is None:
                self._start(t)
            elif w.phase == ENDING:
                # neu gestartet während des Ausrollens -> altes Workout abschließen
                self._finalize(w.stop_at or t, "stopped")
                self._start(t)
            elif w.phase in (PAUSED, LOST):
                w.close_interval(t)
                w.phase, w.phase_since = RUNNING, t
        elif st == "paused":
            if w and w.phase in (RUNNING, LOST):
                w.open_interval("pause", t)
                w.phase, w.phase_since = PAUSED, t
        elif st == "stopped":
            if w is None:
                return
            if w.phase == LOST:
                # Verbindung war weg, inzwischen beendet -> letzten Stand nehmen
                self._finalize(max(w.last_progress_t, w.started_at), "stopped_while_lost")
            elif w.phase != ENDING:
                w.close_interval(t)
                w.phase, w.phase_since, w.stop_at = ENDING, t, t
        elif st == "countdown":
            pass
        else:  # disconnected / unavailable / unknown / None
            if w and w.phase in (RUNNING, PAUSED):
                w.open_interval("lost", t)
                w.phase, w.phase_since = LOST, t
        if self.active:
            self._flush(t, force=True)

    def _start(self, t):
        cur = self.db.execute(
            "INSERT INTO workouts(status, started_at, person) VALUES('active', ?,"
            " (SELECT person FROM workouts ORDER BY started_at DESC LIMIT 1))", (t,))
        self.db.commit()
        w = Workout(id=cur.lastrowid, started_at=t, phase_since=t,
                    last_progress_t=t, last_flush=t)
        # Zähler ab 0 rechnen: läuft das Band schon, zählt das ganze Training.
        # Ein alter Restwert (Strecke bleibt nach Stopp stehen) wird beim
        # Nullsetzen durch das Band automatisch korrigiert.
        for k in COUNTERS:
            v = self.values.get(k)
            if v is not None:
                w.counters[k] = Counter(acc=0.0, seg_start=0.0, last_raw=float(v))
        self.active = w
        log.info("Workout %s gestartet", w.id)
        self._sample(t, speed_changed=True, force=True)

    def _sample(self, t, speed_changed: bool, force: bool = False):
        w = self.active
        if not w or w.phase == LOST:
            return
        if not (force or speed_changed) and t - w.last_sample_t < MIN_GAP_S:
            return
        t = max(t, w.last_sample_t)
        tot = w.totals()
        speed = self.values.get("speed")
        if w.phase == PAUSED:
            speed = 0.0 if speed is None else speed
        w.buffer.append((w.id, t, speed, tot["distance"], tot["duration"],
                         tot["calories"], tot["steps"]))
        w.last_sample_t = t

    def _flush(self, now, force=False):
        w = self.active
        if not w:
            return
        if w.buffer:
            self.db.executemany(
                "INSERT INTO samples(workout_id,t,speed,distance,duration,calories,steps)"
                " VALUES(?,?,?,?,?,?,?)", w.buffer)
            w.buffer.clear()
        tot = w.totals()
        self.db.execute(
            "UPDATE workouts SET distance_km=?, duration_s=?, calories=?, steps=?,"
            " max_speed=?, intervals=?, state_json=? WHERE id=?",
            (tot["distance"], tot["duration"], tot["calories"], tot["steps"],
             w.max_speed, json.dumps(w.intervals), json.dumps(w.state_dict()), w.id))
        self.db.commit()
        w.last_flush = now

    def _finalize(self, ended_at: float, reason: str):
        w = self.active
        if not w:
            return
        w.close_interval(ended_at)
        self._flush(ended_at, force=True)
        self.active = None
        tot = w.totals()
        pauses = [i for i in w.intervals if i["kind"] == "pause" and i["e"] is not None]
        pause_s = sum(i["e"] - i["s"] for i in pauses)
        lost_s = sum(i["e"] - i["s"] for i in w.intervals
                     if i["kind"] == "lost" and i["e"] is not None)
        duration = tot["duration"]
        if duration <= 0:   # Band liefert keine Zeit -> Wandzeit ohne Pausen
            duration = max(0.0, ended_at - w.started_at - pause_s - lost_s)
        if duration < self.min_duration_s:
            log.info("Workout %s verworfen (%.0f s < %.0f s)", w.id, duration,
                     self.min_duration_s)
            self.delete(w.id)
            return
        dist = tot["distance"]
        avg = dist / (duration / 3600.0) if duration > 0 else 0.0
        row = self.db.execute(
            "SELECT MAX(speed) AS m FROM samples WHERE workout_id=? AND t<=?",
            (w.id, ended_at + 0.5)).fetchone()
        max_speed = max(w.max_speed, row["m"] or 0.0)
        spark = self._spark(w.id, w.started_at, ended_at)
        self.db.execute(
            "UPDATE workouts SET status='done', ended_at=?, duration_s=?, distance_km=?,"
            " calories=?, steps=?, avg_speed=?, max_speed=?, pause_s=?, pause_count=?,"
            " intervals=?, spark=?, state_json='{}', end_reason=? WHERE id=?",
            (ended_at, duration, dist, tot["calories"], tot["steps"], avg, max_speed,
             pause_s, len(pauses), json.dumps(w.intervals), json.dumps(spark),
             reason, w.id))
        self.db.commit()
        log.info("Workout %s gespeichert: %.2f km, %.0f s (%s)", w.id, dist, duration, reason)

    def _spark(self, wid, start, end, n=48):
        rows = self.db.execute(
            "SELECT t, speed FROM samples WHERE workout_id=? AND t<=? ORDER BY t",
            (wid, end)).fetchall()
        if not rows or end <= start:
            return []
        span = (end - start) / n
        out = []
        idx = 0
        last = rows[0]["speed"] or 0.0
        for b in range(n):
            lo, hi = start + b * span, start + (b + 1) * span
            vals = []
            while idx < len(rows) and rows[idx]["t"] < hi:
                if rows[idx]["t"] >= lo and rows[idx]["speed"] is not None:
                    vals.append(rows[idx]["speed"])
                idx += 1
            if vals:
                last = sum(vals) / len(vals)
            out.append(round(last, 2))
        return out

    # ------------------------------------------------------------- recovery
    def _recover(self):
        row = self.db.execute(
            "SELECT * FROM workouts WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
        # ältere hängengebliebene "active" Einträge abschließen
        for old in self.db.execute(
                "SELECT id FROM workouts WHERE status='active' AND id<?",
                (row["id"] if row else 1 << 62,)).fetchall():
            self.db.execute("UPDATE workouts SET status='done', end_reason='recovered' "
                            "WHERE id=?", (old["id"],))
        self.db.commit()
        if not row:
            return
        st = json.loads(row["state_json"] or "{}")
        w = Workout(id=row["id"], started_at=row["started_at"])
        for k, d in (st.get("counters") or {}).items():
            if k in w.counters:
                w.counters[k] = Counter.from_dict(d)
        w.intervals = st.get("intervals") or []
        w.last_progress_t = st.get("last_progress_t") or row["started_at"]
        w.last_sample_t = st.get("last_sample_t") or row["started_at"]
        w.last_speed = st.get("last_speed")
        w.max_speed = st.get("max_speed") or 0.0
        now = time.time()
        # bis der aktuelle Zustand vom Band kommt, gilt die Verbindung als weg
        w.open_interval("lost", w.last_sample_t)
        w.phase, w.phase_since, w.last_flush = LOST, w.last_sample_t, now
        self.active = w
        log.info("Offenes Workout %s nach Neustart übernommen", w.id)

    # ------------------------------------------------------------------ reads
    def delete(self, wid: int):
        self.db.execute("DELETE FROM samples WHERE workout_id=?", (wid,))
        self.db.execute("DELETE FROM workouts WHERE id=?", (wid,))
        self.db.commit()

    def set_person(self, wid: int, person: str | None) -> bool:
        cur = self.db.execute("UPDATE workouts SET person=? WHERE id=?", (person, wid))
        self.db.commit()
        return cur.rowcount > 0

    def list_workouts(self):
        rows = self.db.execute(
            "SELECT id, started_at, ended_at, duration_s, distance_km, calories, steps,"
            " avg_speed, max_speed, pause_s, pause_count, spark, person FROM workouts"
            " WHERE status='done' ORDER BY started_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["spark"] = json.loads(d["spark"] or "[]")
            out.append(d)
        return out

    def get_workout(self, wid: int, max_points: int = 900):
        r = self.db.execute("SELECT * FROM workouts WHERE id=?", (wid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d.pop("state_json", None)
        d["intervals"] = json.loads(d["intervals"] or "[]")
        d.pop("spark", None)
        rows = [tuple(x) for x in self.db.execute(
            "SELECT t, speed, distance, duration, calories, steps FROM samples"
            " WHERE workout_id=? ORDER BY t", (wid,)).fetchall()]
        if self.active and self.active.id == wid:
            rows += [tuple(b[1:]) for b in self.active.buffer]
        d["splits"] = compute_splits(rows, d["started_at"], d["intervals"])
        d["samples"] = downsample(rows, max_points)
        return d

    def raw_samples(self, wid: int):
        return [tuple(x) for x in self.db.execute(
            "SELECT t, speed, distance, duration, calories, steps FROM samples"
            " WHERE workout_id=? ORDER BY t", (wid,)).fetchall()]

    def live(self):
        w = self.active
        out = {"pad": dict(self.values), "active": None}
        if w:
            tot = w.totals()
            rows = [tuple(x) for x in self.db.execute(
                "SELECT t, speed, distance, duration FROM samples WHERE workout_id=?"
                " AND t>=? ORDER BY t", (w.id, time.time() - 180)).fetchall()]
            rows += [(b[1], b[2], b[3], b[4]) for b in w.buffer]
            out["active"] = {
                "id": w.id, "started_at": w.started_at, "phase": w.phase,
                "distance_km": tot["distance"], "duration_s": tot["duration"],
                "calories": tot["calories"], "steps": tot["steps"],
                "max_speed": w.max_speed,
                "person": self.db.execute("SELECT person FROM workouts WHERE id=?",
                                          (w.id,)).fetchone()[0],
                "recent": [[round(r[0], 1), r[1]] for r in rows],
            }
        return out


def downsample(rows, max_points):
    """rows: (t, speed, distance, duration, calories, steps). Zeit-Buckets,
    Tempo gemittelt, Zähler = letzter Wert im Bucket."""
    if len(rows) <= max_points:
        return [list(r) for r in rows]
    t0, t1 = rows[0][0], rows[-1][0]
    span = (t1 - t0) / max_points or 1.0
    out, bucket, edge = [], [], t0 + span
    for r in rows:
        if r[0] >= edge and bucket:
            out.append(_merge(bucket))
            bucket = []
            while r[0] >= edge:
                edge += span
        bucket.append(r)
    if bucket:
        out.append(_merge(bucket))
    return out


def _merge(bucket):
    speeds = [b[1] for b in bucket if b[1] is not None]
    last = bucket[-1]
    return [sum(b[0] for b in bucket) / len(bucket),
            (sum(speeds) / len(speeds)) if speeds else None,
            last[2], last[3], last[4], last[5]]


def compute_splits(rows, started_at, intervals):
    """Kilometer-Splits aus Strecke über aktiver Zeit (Zähler des Bandes)."""
    if not rows:
        return []
    use_counter = max((r[3] or 0) for r in rows) > 0
    pauses = [(i["s"], i["e"] or i["s"]) for i in intervals]

    def active_time(r):
        if use_counter:
            return r[3] or 0.0
        t = r[0] - started_at
        for s, e in pauses:
            if e <= r[0]:
                t -= (e - s)
            elif s < r[0]:
                t -= (r[0] - s)
        return max(0.0, t)

    pts = [(r[2] or 0.0, active_time(r)) for r in rows]
    splits, km, prev_d, prev_t = [], 1, 0.0, 0.0
    last_cross_t = 0.0
    for d, t in pts:
        while d >= km and d > prev_d:
            frac = (km - prev_d) / (d - prev_d)
            cross = prev_t + frac * (t - prev_t)
            splits.append({"km": km, "dist": 1.0, "time_s": cross - last_cross_t})
            last_cross_t = cross
            km += 1
        prev_d, prev_t = d, t
    rest = pts[-1][0] - (km - 1)
    if rest >= 0.05:
        splits.append({"km": km, "dist": round(rest, 3),
                       "time_s": pts[-1][1] - last_cross_t})
    for s in splits:
        s["speed"] = s["dist"] / (s["time_s"] / 3600.0) if s["time_s"] > 0 else 0.0
        s["pace_s"] = s["time_s"] / s["dist"] if s["dist"] > 0 else 0.0
    return splits
