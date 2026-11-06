# Laufband-Log

Home-Assistant-App, die Workouts eines PitPat-Walking-Pads aufzeichnet, mit
Verlaufsdiagrammen anzeigt und das Band steuert. Details: [laufband_log/DOCS.md](laufband_log/DOCS.md).

## Screenshots

Mit Demo-Daten (`tests/make_demo.py`) und simuliertem Band (`tests/fake_pad_ha.py`).

<p>
  <img src="docs/screenshots/overview_mobile_dark.png" alt="Übersicht mit Wochenstatistik und Workout-Liste" width="250">
  <img src="docs/screenshots/detail_mobile_dark.png" alt="Workout-Detail mit Tempo- und Streckendiagramm" width="250">
  <img src="docs/screenshots/ctl_running.png" alt="Steuerung bei laufendem Band" width="250">
</p>

<img src="docs/screenshots/overview_desktop_light.png" alt="Übersicht im hellen Design am Desktop" width="600">

## Installation

1. Einstellungen → Apps → App Store → ⋮ → Repositories →
   `https://github.com/TimMixedIt/Laufband-Log` hinzufügen.
2. „Laufband-Log“ installieren und starten. Erscheint als Seitenleisten-Eintrag „Laufband“.

Voraussetzung: HACS-Integration `scphyle/ha-pitpat-treadmill` mit den `walkingpad_*`-Entitäten.
