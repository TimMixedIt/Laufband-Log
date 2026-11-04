# Laufband-Log

Home-Assistant-App (Add-on), die Workouts von Tims DeerRun-Walking-Pad (PitPat,
BLE-Name „PitPat-T01“, Firmware 37) aufzeichnet, wie Apple Fitness anzeigt und das
Band steuert. Sprache: Deutsch (UI, Kommentare, Commits).

## Umgebung
- Home Assistant OS mit Supervisor auf Proxmox; Band hängt per ESPHome-Bluetooth-Proxy
  an der HACS-Integration `scphyle/ha-pitpat-treadmill` (Domain `pitpat_ba04`).
- Entitäten: `sensor.walkingpad_{state,speed,distance,duration,calories,steps,max_speed}`,
  `button.walkingpad_{start,pause_resume,stop}`, `number.walkingpad_speed` (0–6, Schritt 0,1).
- `state`: countdown | running | paused | stopped | disconnected.

## Beobachtetes Verhalten des Bandes (wichtig für die Logik)
- Nach `stopped` rollt das Band noch ~6 s aus; Speed fällt erst danach auf 0.
- ~6 s nach Stopp setzt es `duration` und `calories` auf 0; `distance` bleibt stehen
  und wird erst beim nächsten Start genullt (alter Restwert!).
- Speed-Updates kommen bei Änderungen ca. alle 0,5 s.
- Schritte meldet das Band aktuell als 0.

## Aufbau
- `laufband_log/` = die App (so wie sie nach `/addons/laufband_log` kommt).
  - `app/recorder.py` – reine Logik: Workout-Erkennung (Phasen running/paused/lost/ending),
    reset-feste Zähler (`Counter`), SQLite (`/data/workouts.db`), Splits, Downsampling.
  - `app/ha_client.py` – Websocket zu HA: `subscribe_entities` (komprimiertes Format a/c/r),
    `call_service` für die Steuerung.
  - `app/main.py` – aiohttp: `/api/live`, `/api/workouts[/id[/csv]]`, `POST /api/control`.
    Unter Supervisor nur Ingress (172.30.32.2), Token = SUPERVISOR_TOKEN.
  - `app/static/` – Vanilla-JS-SPA ohne Build. Relative URLs (Ingress!), Hash-Routing.
    Diagramme sind selbst gezeichnetes SVG. 7-Segment-Schrift DSEG7 (OFL).
- `tests/` – Simulator und Fake-HA.

## Testen (ohne echtes Band)
```bash
pip install aiohttp playwright
python3 tests/test_recorder.py                 # Logik: Pause, Abbruch, Reset, Neustart
python3 tests/fake_pad_ha.py &                 # steuerbares Fake-Band auf :18123
DATA_DIR=/tmp/ll HA_URL=http://127.0.0.1:18123 HA_TOKEN=x PORT=18099 python3 laufband_log/app/main.py
python3 tests/ctl_test.py http://127.0.0.1:18099 /tmp   # Steuerung per Playwright
python3 tests/make_demo.py /tmp/ll             # drei Wochen Demo-Workouts
```

## Deploy / Update
Ordner `laufband_log` nach `/addons/laufband_log` auf HA kopieren (Studio Code Server
oder Samba), `version` in `config.yaml` erhöhen, App Store → Nach Updates suchen →
Aktualisieren. Workouts bleiben in `/data` erhalten.

## Regeln
- Sicherheit Steuerung: Start nur per Halten (0,8 s) und nur aus dem Stillstand; Tempo nur
  bei `running`, begrenzt auf `max_control_speed`. Stopp immer sofort. Nichts automatisch starten.
- Fehler, Tool-Eigenheiten und falsche Annahmen sofort in Tims Obsidian-Notiz
  `Fehler-Log.md` (iCloud Drive/Obsidian) eintragen; Format
  `YYYY-MM-DD | Kontext | Fehler | Learning / Fix`. Vor neuen Techniken dort nachsehen.

## Ideen / offen
- Herzfrequenz der Apple Watch einbinden (z. B. Health Auto Export → Webhook).
- Erster echter Image-Build auf HA steht noch aus (im Cloud-Workspace kein Docker).
