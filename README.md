# Was der Grosse Rat ausgibt

Übersicht der Ausgaben, die der Grosse Rat Basel-Stadt seit dem 1. Januar 2026 bewilligt hat, mit dem Stimmverhalten der Parteien. Herausgeberin: FDP.Die Liberalen Basel-Stadt. Gestaltet nach dem Auftritt von fdp-bs.ch.

## Was gezählt wird

- Ratschläge und Ausgabenberichte, denen der Grosse Rat zugestimmt hat. Der Betrag stammt aus dem Grossratsbeschluss (PDF).
- Budget, Rechnung, Nachtragskredite und Kreditübertragungen zählen nicht.
- Einmalige Ausgaben und befristete Beiträge zählen mit dem Gesamtbetrag, unbefristet wiederkehrende Ausgaben separat pro Jahr.
- Stimmverhalten: Schlussabstimmung, sonst letzte Abstimmung zum Geschäft am Sitzungstag. Eine Partei hat zugestimmt, wenn die Mehrheit ihrer Ratsmitglieder Ja gestimmt hat. Das jgb zählt zu den Grünen.
- Budgetpostulate mit «Zustimmung zur Budgeterhöhung», zugeordnet der Partei der Erstunterzeichnerin oder des Erstunterzeichners.
- Überwiesene Motionen und Anzüge, zugeordnet der Partei der Erstunterzeichnerin oder des Erstunterzeichners. Kosten nur, wenn sie in `korrekturen.csv` eingetragen sind.

## Beträge prüfen und korrigieren

Nach jedem Lauf zeigt `pruefliste.md` zu jedem Geschäft die Textstelle, aus der der Betrag stammt. Stimmt etwas nicht, in `korrekturen.csv` eine Zeile ergänzen (Anleitung steht in der Datei). Nach dem Speichern baut GitHub die Seite automatisch neu.

## Wie es läuft

- `build.py` holt die Daten von data.bs.ch (Datensätze 100314, 100311, 100313, 100186, 100307), liest die Beschluss-PDFs mit pdftotext und baut `docs/index.html` und `docs/data.json`. Gelesene PDFs werden in `cache/pdf` gespeichert.
- `.github/workflows/update.yml` läuft jeden Morgen um 05:23 Uhr. Sobald eine neue Sitzung in den offenen Daten ist, erscheint sie auf der Seite.
- Manuell starten: Actions, «Grossrat-Ausgaben aktualisieren», «Run workflow».
- Die Seite wird über GitHub Pages aus dem Ordner `docs` veröffentlicht.

Quelle: Grosser Rat des Kantons Basel-Stadt, Open Data Basel-Stadt (data.bs.ch). Rechtlich massgebend sind allein die Beschlüsse des Grossen Rates.
