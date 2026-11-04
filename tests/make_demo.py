"""Erzeugt Demo-Workouts der letzten drei Wochen über den echten Recorder."""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "laufband_log", "app"))
sys.path.insert(0, HERE)
from recorder import Recorder  # noqa: E402
from sim import Pad, drive     # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
db = os.path.join(out, "workouts.db")
if os.path.exists(db):
    os.remove(db)
rec = Recorder(db)
random.seed(7)

now = time.time()
lt = time.localtime(now)
today0 = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
plan = [  # (Tage zurück, Uhrzeit, Minuten, Besonderheit)
    (19, 9.5, 25, None), (17, 13.2, 40, None), (16, 10.0, 20, None),
    (14, 15.5, 35, "pause"), (12, 9.1, 50, None), (11, 14.0, 30, None),
    (9, 11.3, 45, None), (7, 16.0, 30, None), (6, 10.4, 25, None),
    (5, 13.7, 60, "pause"), (2, 9.2, 32, None), (1, 15.1, 41, "lost"),
    (0, 15.67, 24, "pause"),
]
for days, hour, minutes, special in plan:
    t0 = today0 - days * 86400 + hour * 3600
    pad = Pad(t0)
    run = lambda s: drive(pad, rec, s)  # noqa: E731
    rec.feed([("state", "stopped", t0), ("speed", 0.0, t0), ("distance", 0.04, t0),
              ("duration", 0, t0), ("calories", 0, t0), ("steps", 0, t0)])
    run(5)
    base = random.choice([3.4, 3.6, 3.8, 4.0])
    pad.countdown_and_start(base, run)
    remaining = minutes * 60
    seg = 0
    while remaining > 0:
        chunk = min(remaining, random.randint(3, 8) * 60)
        if special == "pause" and seg == 2:
            pad.set_state("paused"); pad.target = 0
            run(random.randint(70, 180))
            pad.set_state("running")
        if special == "lost" and seg == 2:
            pad.disconnect(); run(45); pad.reconnect()
        pad.target = round(min(5.6, max(2.8, base + random.choice([-0.6, -0.3, 0, 0.3, 0.6, 1.0]))), 1)
        run(chunk)
        remaining -= chunk
        seg += 1
    pad.stop()
    run(20)

for w in rec.list_workouts():
    print(w["id"], time.strftime("%a %d.%m %H:%M", time.localtime(w["started_at"])),
          f"{w['distance_km']:.2f} km {w['duration_s']/60:.0f} min")
