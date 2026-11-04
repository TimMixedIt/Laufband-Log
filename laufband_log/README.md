# Laufband-Log – Installation

Lokale Home-Assistant-App (Add-on). Erscheint nach der Installation als
**Laufband** in der Seitenleiste.

## 1. Ordner nach `/addons` kopieren

Der Ordner `laufband_log` muss als `/addons/laufband_log` auf dem
Home-Assistant-Server liegen (mit `config.yaml` direkt darin).

Am einfachsten mit **Studio Code Server**:

1. Studio Code Server öffnen, über das Menü *Terminal → Neues Terminal*
   ein Terminal öffnen.
2. Die Datei `laufband_log.zip` per Drag & Drop in den Explorer links ziehen
   und dort im Ordner `/addons` ablegen (oder über *Datei → Ordner öffnen* →
   `/addons` öffnen und hineinziehen).
3. Im Terminal entpacken:
   ```
   cd /addons && unzip -o laufband_log.zip && rm laufband_log.zip
   ```
   Ohne `unzip`: `python3 -m zipfile -e laufband_log.zip .`

Alternativ über das Samba-Share `addons` oder per SSH/scp.

## 2. Installieren

1. *Einstellungen → Apps → App Store* öffnen.
2. Oben rechts ⋮ → **Nach Updates suchen**.
3. Unter **Lokale Apps** erscheint *Laufband-Log* → **Installieren**.
   Home Assistant baut das Image lokal (1–2 Minuten).
4. **Starten** und **In Seitenleiste anzeigen** aktivieren.

Die Entitäten sind schon auf `sensor.walkingpad_*` eingestellt. Im Tab
*Protokoll* sollte stehen: `Mit Home Assistant verbunden, 6 Entitäten abonniert`.

## Update

Neue Version in `/addons/laufband_log` überschreiben, in `config.yaml` die
`version` erhöhen, dann im App Store *Nach Updates suchen* → *Aktualisieren*.
Die gespeicherten Workouts bleiben erhalten.
