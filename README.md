# ChemLab Control Tower

Lokaler Plotly-Dash-Demonstrator für Proben, Analyseaufträge, Ergebnisprüfung und Statistik. **Alle Daten und Spezifikationen sind synthetische Demo-Annahmen.** Das Projekt ist kein validiertes LIMS, kein GMP-System und nicht für reale Labor-, Qualitäts- oder Freigabeentscheidungen geeignet.

## Schnellstart (Windows PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Öffne anschließend <http://127.0.0.1:8050>. Bei der ersten Ausführung legt die Anwendung eine lokale SQLite-Datenbank an und lädt einmalig Demo-Daten. Es wird **kein Benutzerkonto automatisch erzeugt**; die Anmeldung ist erforderlich.

Für eine neue Umgebung:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

## Lokale Konten

Ein Administrator-Konto kann einmalig über die CLI angelegt werden. Das Kennwort wird interaktiv eingegeben und gehasht gespeichert:

```powershell
.\.venv\Scripts\python.exe -m services.auth_service --username admin --role Administrator
```

Laboranten- und Laborleitungs-Konten müssen einem passenden Demo-Mitarbeiter zugeordnet werden, zum Beispiel:

```powershell
.\.venv\Scripts\python.exe -m services.auth_service --username labor --role Laborant --employee-id E-01
.\.venv\Scripts\python.exe -m services.auth_service --username leitung --role Laborleitung --employee-id E-06
```

Alternativ können Administratoren in der Operations-Ansicht weitere lokale Konten anlegen. Laboranten können Aufträge übernehmen und bearbeiten; Laborleitungen können Proben/Aufträge anlegen und Ergebnisse fachlich freigeben. Die Aktionen werden anhand des angemeldeten Kontos serverseitig autorisiert. Dies ist eine lokale Demo-Anmeldung, keine Unternehmens- oder Mehrfaktor-Authentifizierung.

## Persistenz und Konfiguration

- Standarddatenbank: `data/chemlab.sqlite3`. Bestehende Daten bleiben bei Neustarts erhalten; nur eine neue Datenbank erhält einmalig die synthetischen Ausgangsdaten.
- `CHEMLAB_DATABASE_PATH` ändert den SQLite-Dateipfad.
- `CHEMLAB_SESSION_SECRET` setzt einen stabilen lokalen Flask-Session-Schlüssel. Ohne diese Umgebungsvariable wird ein zufälliger Schlüssel je App-Start erzeugt und bestehende Anmeldungen verfallen beim Neustart.
- Das Repository bietet SQLite-Transaktionen, Audit-Ereignisse und eine Backup-Funktion. SQLite-Datenbank- und Backup-Dateien sind von Git ausgeschlossen.

**Vor einem Datenbankwechsel oder manuellen Eingriff die Datenbank sichern.** Die enthaltenen Demo-Spezifikationen, Prioritätsregeln, Zeitvorgaben, QC-Grenzen und die Mindestdatenmenge für Prozessfähigkeitskennzahlen sind nicht fachlich validiert.

## Aktueller Funktionsumfang

- Probenanlage mit mehreren getrennten Analyseaufträgen und idempotenter Absicherung doppelter Formularübermittlungen.
- Persistente Queue, Suche, Frist-/Prioritäts-KPIs, Workflow-Aktionen und Rollenprüfung.
- Versionierte Messwerte mit Grenzwertstatus, Ergebnisprüfung/Freigabe und sichtbarer Historie.
- Statistik über aktuelle freigegebene Ergebnisse, unter anderem gefiltert nach Produkt, Methode, Probenart, Parameter, Qualität und Zeitraum.
- Audit-Ereignisse für wesentliche Anlage-, Mess- und Statusänderungen.

## Noch nicht vollständig umgesetzt

Die Anwendung ist weiterhin ein Demonstrator und erfüllt noch nicht den vollständigen ursprünglichen Anforderungskatalog. Unter anderem fehlen eine vollständige Prüfplan-/Spezifikationsversionierung und Übernahme je Probe, Probe-Detailansicht mit Änderungsfunktionen, manuelle Prioritäts-/Fristkorrekturen, kontrollierte Wiedereröffnung und Neuzuweisung, eine vollständige OOS-Fallbewertung sowie die Qualitätsentscheidung auf Probenebene. Prüfplanregeln und weitere fachliche Vorgaben sind teilweise nur als Demo-Defaults umgesetzt.

Ergebnisfreigabe bezieht sich ausschließlich auf eine einzelne Demo-Ergebnisversion und ist **keine** Chargen-, Produkt- oder Produktionsfreigabe. Cp/Cpk und Kontrollgrenzen werden bei unzureichender bzw. nicht homogener Datenbasis ausgeblendet; diese Demo-Heuristik ist keine validierte Statistikregel.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Die Tests prüfen unter anderem Workflow-Übergänge, Rollenbeschränkungen, lokale Konten, SQLite-Persistenz/Transaktionen, doppelte Formularübermittlungen sowie Queue- und Statistikfilter.
