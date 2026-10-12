# ChemLab Control Tower

Ein vollständiger, lokaler Plotly-Dash-Prototyp für Laborworkflow, Qualitätsbewertung und Statistik. **Alle Daten und Spezifikationen sind synthetische Demo-Annahmen.** Das Projekt ist kein validiertes LIMS, kein GMP-System und nicht für reale Freigabeentscheidungen geeignet.

## Schnellstart

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Danach: `http://127.0.0.1:8050` im Browser öffnen.

## Tests

```bash
python -m pytest
```

## Projektmodule

- **Laboratory Operations:** Analyse-Queue, Prioritäten und Demo-SLAs.
- **Quality Control:** PASS, grenznah und OOS nach synthetischen Spezifikationen.
- **Statistics:** Zeitreihe, 3-Sigma-Kontrollgrenzen, Cp und Cpk.

## Wichtige Architekturregel

`SAMPLE ≠ ANALYSIS_TASK ≠ RESULT` und `METHOD ≠ INSTRUMENT`. Die später ersetzbare In-Memory-Repository-Schicht ist bewusst von Dash getrennt.
