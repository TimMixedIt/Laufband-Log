# Laufband-Log

Zeichnet jedes Training auf dem Walking Pad automatisch auf und zeigt es wie in
Apple Fitness an: Übersicht pro Woche, Liste aller Workouts und pro Workout
Kennzahlen, Geschwindigkeits- und Streckenverlauf sowie Kilometer-Splits.

Die Daten kommen aus den Sensoren der PitPat-Integration. Die App braucht kein
eigenes Token; sie meldet sich über den Supervisor bei Home Assistant an.

## So wird ein Workout erkannt

- **Start:** Das Band wechselt auf `running`.
- **Pause:** `paused` wird als Pause markiert (schraffiert im Diagramm). Nach
  `max_pause_minutes` gilt das Training als beendet.
- **Verbindungsabbruch:** Ist das Band kurz nicht erreichbar, läuft das Workout
  weiter. Erst nach `max_disconnect_minutes` wird mit dem letzten Stand gespeichert.
- **Ende:** `stopped`. Das Band rollt danach noch ein paar Sekunden aus und
  setzt Zeit und Kalorien auf 0; beides wird abgefangen.
- Trainings unter `min_duration_seconds` (Standard 60 s) werden verworfen,
  damit kurze Testläufe die Statistik nicht verfälschen.

Zeit, Strecke und Kalorien stammen direkt vom Band. Die Kalorien sind eine
Schätzung des Bandes.

## Steuerung

In der Live-Anzeige oben lässt sich das Band bedienen. Die Befehle gehen an die
Buttons und den Tempo-Regler der PitPat-Integration.

- **Starten/Fortsetzen:** Knopf 0,8 s gedrückt halten. Ein kurzer Tipp startet nichts.
- **Pause** und **Stopp:** ein Tipp. Stopp ist immer sichtbar, solange das Band läuft.
- **Tempo:** − / + in 0,2-km/h-Schritten oder 3, 4, 5 km/h direkt. Mehrere Tipps
  werden gesammelt und als ein Befehl gesendet. Höchstwert: `max_control_speed`.
- Das Tempo lässt sich nur bei laufendem Band ändern. Starten geht nur aus dem Stillstand.

Wichtig: Reißt die Bluetooth-Verbindung ab, läuft das Band weiter. Die
Fernbedienung bleibt der sichere Not-Aus.

## Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `state_entity` … `steps_entity` | `sensor.walkingpad_*` | Sensoren der PitPat-Integration |
| `min_duration_seconds` | 60 | Kürzere Trainings werden nicht gespeichert |
| `max_pause_minutes` | 30 | Pause, nach der das Training automatisch endet |
| `max_disconnect_minutes` | 10 | Verbindungsabbruch, nach dem das Training endet |
| `start_button`, `pause_button`, `stop_button` | `button.walkingpad_*` | Buttons der Integration |
| `speed_number` | `number.walkingpad_speed` | Tempo-Regler der Integration |
| `max_control_speed` | 6.0 | Höchstes Tempo, das die Seite einstellen darf |
| `people` | Tim, Freundin | Wer das Band nutzt (siehe unten) |

## Mehrere Personen

Stehen in `people` mindestens zwei Namen, lässt sich pro Workout auswählen, wer
gelaufen ist: live in der Anzeige oben und in der Detailansicht. Ein neues
Workout übernimmt die Person des vorherigen. In der Übersicht filtern die
Knöpfe Wochenstatistik und Liste nach Person. Wird ein Name in `people`
umbenannt, behalten alte Workouts den alten Namen und erscheinen nur unter „Alle“.

## Daten

Alle Workouts liegen in `/data/workouts.db` (SQLite) im App-Ordner und sind
damit in jedem Home-Assistant-Backup enthalten. Jedes Workout lässt sich in
der Detailansicht als CSV exportieren.
