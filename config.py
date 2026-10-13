"""Central, deliberately synthetic demo configuration."""
from datetime import timedelta
import os
from pathlib import Path

APP_TITLE = "ChemLab Control Tower"
DATABASE_PATH = Path(os.environ.get(
    "CHEMLAB_DATABASE_PATH",
    str(Path(__file__).resolve().parent / "data" / "chemlab.sqlite3"),
))
SEED = 20261006
PRIMARY = "#004A96"
COLORS = {"pass": "#16794A", "near_limit": "#B06D00", "oos": "#B42318", "neutral": "#667085"}
SLA_HOURS = {"Routine": 24, "Produktion dringend": 4, "Stabilitätsprobe": 72}
DEMO_DAYS = 45
NEAR_LIMIT_FRACTION = 0.10
MIN_STAT_N = 2
DEMO_RULES = {
    "valid_lims": "Die Anwendung ist ein Demonstrator und kein validiertes LIMS oder GMP-System.",
    "result_model": "Probe, Analyseauftrag und Ergebnis sind getrennte fachliche Objekte.",
    "method_model": "Methode und Gerät sind getrennte Entitäten; sie werden separat modelliert.",
    "data_scope": "Daten sind synthetische Demo-Werte ohne reale Freigabe- oder Produktionswirkung.",
    "priority": "OFFEN/DEMO: Routine und Stabilitätsprobe -> Normal; Produktion dringend -> Hoch; Kritisch nur manuell.",
    "due_soon": "OFFEN/DEMO: bald fällig bedeutet höchstens 20 Prozent der SLA-Dauer bis zum Termin.",
    "default_plan": "OFFEN/DEMO: bestehende Produktbasis-Methoden sind vorläufige Pflichtanalysen.",
    "calculation": "OFFEN/DEMO: Ergebnisaufnahme entspricht Einzelwert-Auswahl; keine automatische Wiederholungsmittelung.",
    "near_limit": "OFFEN/DEMO: Grenznähe ist ein Hinweis innerhalb der Spezifikationsgrenzen.",
    "permissions": "OFFEN/DEMO: lokaler Benutzerwechsel ist nicht authentifiziert und kein Sicherheitsmerkmal.",
}


def deadline(received_at, order_type: str):
    return received_at + timedelta(hours=SLA_HOURS[order_type])
