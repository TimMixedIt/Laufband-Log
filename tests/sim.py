"""Simuliert das PitPat-Band (Verhalten wie im echten HA-Verlauf beobachtet)."""
import math
import random


class Pad:
    def __init__(self, t0, stale_distance=0.041):
        self.t = t0
        self.state = "stopped"
        self.speed = 0.0
        self.target = 0.0
        self.dist = stale_distance
        self.dur = 0.0
        self.kcal = 0.0
        self.connected = True
        self.events = []          # (key, value, t)
        self.pending_reset = None
        self._acc_dur = 0.0

    def emit(self, key, value):
        if self.connected or key == "state":
            self.events.append((key, value, self.t))

    def set_state(self, s):
        self.state = s
        self.emit("state", s if self.connected else "disconnected")

    def disconnect(self):
        self.connected = False
        self.events.append(("state", "disconnected", self.t))
        for k in ("speed", "distance", "duration", "calories"):
            self.events.append((k, None, self.t))

    def reconnect(self, reset_counters=False):
        self.connected = True
        if reset_counters:
            self.dist = self.dur = self.kcal = 0.0
        self.emit("state", self.state)
        self.emit("speed", round(self.speed, 1))
        self.emit("distance", round(self.dist, 3))
        self.emit("duration", int(self.dur))
        self.emit("calories", int(self.kcal))

    def step(self, dt=0.5):
        """Halbe Sekunde vorspulen."""
        self.t += dt
        old_speed = self.speed
        if self.state == "running":
            # Band beschleunigt/bremst ca. 0.4 km/h pro 0.5 s
            if abs(self.target - self.speed) > 0.05:
                self.speed += max(-0.4, min(0.4, self.target - self.speed))
        else:
            if self.speed > 0:
                self.speed = max(0.0, self.speed - 0.35)
        self.speed = round(self.speed, 1)
        if self.speed != old_speed:
            self.emit("speed", self.speed)
        if self.state == "running":
            self.dist += self.speed * dt / 3600.0
            self._acc_dur += dt
            if self._acc_dur >= 1.0:
                self._acc_dur -= 1.0
                self.dur += 1
                self.kcal += self.speed * 0.012 + 0.004
                self.emit("duration", int(self.dur))
                self.emit("distance", round(self.dist, 3))
                if int(self.kcal) != int(self.kcal - self.speed * 0.012 - 0.004):
                    self.emit("calories", int(self.kcal))
        if self.pending_reset and self.t >= self.pending_reset:
            self.pending_reset = None
            self.dur = 0.0
            self.kcal = 0.0
            self.emit("duration", 0)
            self.emit("calories", 0)

    def stop(self):
        self.target = 0.0
        self.set_state("stopped")
        self.pending_reset = self.t + 6.0

    def countdown_and_start(self, target, run):
        self.set_state("countdown")
        run(1.0)
        self.dist = 0.0
        self.emit("distance", 0.0)
        run(3.0)
        self.set_state("running")
        self.speed = 1.0
        self.emit("speed", 1.0)
        self.target = target


def drive(pad, rec, seconds, tick_every=1.0, jitter=True, on_event=None):
    """Lässt das Band `seconds` laufen und füttert den Recorder."""
    end = pad.t + seconds
    next_tick = pad.t
    while pad.t < end - 1e-9:
        pad.step(0.5)
        if pad.events:
            rec.feed(pad.events)
            pad.events = []
        if pad.t >= next_tick:
            rec.tick(pad.t)
            next_tick = pad.t + tick_every
