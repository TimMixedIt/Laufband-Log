import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "laufband_log", "app"))
sys.path.insert(0, HERE)

from recorder import Recorder  # noqa: E402
from sim import Pad, drive     # noqa: E402

DB = os.path.join(HERE, "test.db")
if os.path.exists(DB):
    os.remove(DB)

T0 = 1_762_268_400.0  # 4.11.2026 16:00 (ungefähr)
rec = Recorder(DB)
pad = Pad(T0)
run = lambda s: drive(pad, rec, s)  # noqa: E731

# Ausgangslage wie im echten Verlauf: gestoppt, Strecke 0.041 steht noch da
rec.feed([("state", "stopped", T0), ("speed", 0.0, T0), ("distance", 0.041, T0),
          ("duration", 0, T0), ("calories", 0, T0), ("steps", 0, T0)])
run(30)

# --- Workout A: lang, mit Pause, Verbindungsabbruch, Add-on-Neustart -------
pad.countdown_and_start(3.5, run)
expected_run_s = 0
run(8 * 60)
pad.target = 4.2
run(10 * 60)
pad.set_state("paused"); pad.target = 0
run(120)
pad.set_state("running"); pad.target = 4.0
run(4 * 60)
pad.disconnect()
run(40)
pad.reconnect()
run(3 * 60)
# Add-on-Neustart: neue Recorder-Instanz auf derselben DB
rec = Recorder(DB)
run(20)  # währenddessen keine Daten (HA verbindet erst wieder)
pad.reconnect()  # Initialzustand nach Wiederverbindung
pad.target = 4.5
run(5 * 60)
true_dist_A = pad.dist
true_dur_A = pad.dur
pad.stop()
run(30)
assert rec.active is None, "Workout A sollte abgeschlossen sein"

# --- Workout B: kurzer Testlauf (38 s) -> wird verworfen --------------------
run(60)
pad.countdown_and_start(5.9, run)
run(38)
pad.stop()
run(30)

# --- Workout C: Abbruch mit Zähler-Reset auf dem Band -----------------------
run(120)
pad.countdown_and_start(3.0, run)
run(6 * 60)
d1, du1 = pad.dist, pad.dur
pad.disconnect()
run(30)
pad.reconnect(reset_counters=True)
run(4 * 60)
true_dist_C = d1 + pad.dist
true_dur_C = du1 + pad.dur
pad.stop()
run(30)

ws = rec.list_workouts()
print(f"{len(ws)} Workouts gespeichert")
for w in ws:
    print(f"  #{w['id']}: {w['distance_km']:.3f} km, {w['duration_s']:.0f} s, "
          f"Ø {w['avg_speed']:.2f} km/h, max {w['max_speed']:.1f}, "
          f"{w['calories']:.0f} kcal, Pausen {w['pause_count']} / {w['pause_s']:.0f} s")
print(f"Erwartet A: {true_dist_A:.3f} km, {true_dur_A:.0f} s")
print(f"Erwartet C: {true_dist_C:.3f} km, {true_dur_C:.0f} s")

assert len(ws) == 2, "B (38 s) sollte verworfen sein"
C, A = ws[0], ws[1]
assert abs(A["distance_km"] - true_dist_A) < 0.002, A["distance_km"]
assert abs(A["duration_s"] - true_dur_A) <= 1, A["duration_s"]
assert A["pause_count"] == 1 and 115 <= A["pause_s"] <= 125, A
assert abs(A["max_speed"] - 4.5) < 0.05
assert abs(C["distance_km"] - true_dist_C) < 0.002, C["distance_km"]
assert abs(C["duration_s"] - true_dur_C) <= 1, C["duration_s"]

det = rec.get_workout(A["id"])
print("Intervalle A:", [(round(i["s"] - A["started_at"]), round(i["e"] - A["started_at"]), i["kind"])
                        for i in det["intervals"]])
print("Splits A:", [(s["km"], round(s["dist"], 3), round(s["time_s"]), round(s["speed"], 2))
                    for s in det["splits"]])
print("Punkte A:", len(det["samples"]), "| Rohpunkte:", len(rec.raw_samples(A["id"])))
print("Spark A:", A["spark"][:12], "...")
# --- Person: neues Workout übernimmt die Person des letzten ----------------
assert C["person"] is None
assert rec.set_person(C["id"], "Freundin") and not rec.set_person(99999, "Tim")
run(60)
pad.countdown_and_start(3.0, run)
run(90)
assert rec.live()["active"]["person"] == "Freundin"
pad.stop()
run(30)
assert rec.list_workouts()[0]["person"] == "Freundin"

# --- Apple-Watch-Daten: Zuordnung per Überschneidung, Quelle ohne Doppelzählung --
wA = rec.get_workout(A["id"])
s0, e0 = wA["started_at"], wA["ended_at"]
hr = [(s0 - 300 + i * 5, 90 + (i % 20)) for i in range(int((e0 - s0 + 600) / 5))]
steps = [(s0 - 600, s0 + 600, 1200, "Watch"),     # halb drin -> 600
         (s0 + 600, e0, 3000, "Watch"),
         (s0, e0, 500, "iPhone")]                  # andere Quelle, weniger -> ignoriert
res = rec.attach_health(s0 - 120, e0 + 60, hr, steps, "Tim")
assert res and res["id"] == A["id"], res
assert res["watch_steps"] == 3600, res
inside = [b for t, b in hr if s0 <= t <= e0]
assert res["hr_count"] == len(inside) and res["hr_max"] == max(inside)
again = rec.attach_health(s0 - 120, e0 + 60, hr, steps, None)   # erneut senden ersetzt
assert again["hr_count"] == res["hr_count"]
wA = rec.get_workout(A["id"])
assert wA["person"] == "Tim" and len(wA["heart_rate"]) == res["hr_count"]
assert rec.attach_health(1, 2, hr, steps) is None

# --- Migration: alte DB ohne Spalte person ---------------------------------
import sqlite3  # noqa: E402
OLD = os.path.join(HERE, "old.db")
if os.path.exists(OLD):
    os.remove(OLD)
con = sqlite3.connect(OLD)
con.execute("CREATE TABLE workouts (id INTEGER PRIMARY KEY, status TEXT NOT NULL, started_at REAL NOT NULL,"
            " ended_at REAL, duration_s REAL, distance_km REAL, calories REAL, steps REAL, avg_speed REAL,"
            " max_speed REAL, pause_s REAL, pause_count INTEGER, intervals TEXT, spark TEXT,"
            " state_json TEXT, end_reason TEXT)")
con.execute("INSERT INTO workouts(status, started_at, spark) VALUES('done', 1, '[]')")
con.commit(); con.close()
assert Recorder(OLD).list_workouts()[0]["person"] is None
os.remove(OLD)

print("ALLE TESTS OK")
