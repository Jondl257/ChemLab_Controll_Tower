from dash import dcc, html, dash_table
import plotly.express as px

from components.ui import kpi
from config import COLORS
from domain.enums import TaskStatus
from services.analytics_service import result_view, sample_quality_view


OOS_CASE_COLUMNS = [
    "case_id", "status", "result_id", "sample_id", "task_id",
    "result_version", "opened_at", "opened_by", "initial_description",
    "root_cause", "corrective_action", "closure_rationale",
    "closed_at", "closed_by",
]
OOS_CASE_LABELS = [
    "Fall", "Status", "Ergebnis", "Probe", "Auftrag", "Version",
    "Eröffnet", "Eröffnet von", "Erstbeschreibung", "Ursache",
    "Maßnahme", "Abschlussbegründung", "Abgeschlossen", "Abgeschlossen von",
]


def oos_case_records(repo):
    records = repo.table("oos_cases")[OOS_CASE_COLUMNS].fillna("").astype(str).to_dict("records")
    for row in records:
        row["id"] = row["case_id"]
    return records


def layout(repo):
    results = result_view(repo)
    sample_quality = sample_quality_view(repo)
    current = results.loc[results.is_current.astype(bool)].copy()
    oos_results = results.loc[results.quality_status.eq("OOS")].copy()
    oos_result_options = [
        {
            "label": (
                f"{row.result_id} · {row.sample_id} · {row.task_id} · "
                f"{row.parameter}: {row.value} {row.unit} · Version {row.result_version}"
            ),
            "value": row.result_id,
        }
        for row in oos_results.itertuples()
    ]
    counts = current.quality_status.value_counts()
    total = len(current)
    oos = int(counts.get("OOS", 0))
    review_tasks = current.loc[
        (current.status == TaskStatus.REVIEW_REQUIRED.value)
        & (current.review_status != "freigegeben")
    ].copy()
    if review_tasks.empty:
        review_tasks["id"] = []
    else:
        review_tasks["id"] = review_tasks.task_id
    review_columns = [
        "task_id", "sample_id", "product", "method", "parameter",
        "value", "unit", "quality_status", "lsl", "usl",
        "specification_version", "calculation_rule", "comment",
    ]
    review_table = dash_table.DataTable(
        review_tasks[review_columns + ["id"]].to_dict("records"),
        [{"name": label, "id": column} for column, label in (
            ("task_id", "Auftrag"), ("sample_id", "Probe"), ("product", "Produkt"),
            ("method", "Methode"), ("parameter", "Parameter"), ("value", "Messwert"),
            ("unit", "Einheit"), ("quality_status", "Spezifikationsstatus"),
            ("lsl", "Untergrenze"), ("usl", "Obergrenze"),
            ("specification_version", "Spezifikationsversion"),
            ("calculation_rule", "Berechnungsregel"), ("comment", "Kommentar"),
        )],
        id="qc-review-list", row_selectable="single", page_size=8,
        sort_action="native", filter_action="native",
    )
    fig = px.bar(
        current.groupby(["product", "quality_status"]).size().reset_index(name="Anzahl"),
        x="product", y="Anzahl", color="quality_status", barmode="stack",
        color_discrete_map={"PASS": COLORS["pass"], "GRENZNAH": COLORS["near_limit"], "OOS": COLORS["oos"]},
        title="Aktuell maßgebliche Demo-Ergebnisse nach Produkt",
    )
    detail_columns = [
        "sample_id", "task_id", "product", "method", "parameter", "value", "unit",
        "quality_status", "validity_status", "review_status", "result_version",
        "specification_version", "measured_at", "released_at", "comment",
    ]
    details = dash_table.DataTable(
        results[detail_columns].to_dict("records"),
        [{"name": name.replace("_", " ").title(), "id": name} for name in detail_columns],
        page_size=12, sort_action="native", filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Arial", "fontSize": 12, "padding": "8px", "textAlign": "left"},
    )
    return html.Div([
        html.H2("Prüfung und fachliche Ergebnisfreigabe"),
        html.P(
            "Eine freigegebene OOS-Ergebnisversion bleibt OOS. Diese Demo zeigt Ergebnis-"
            "Freigaben getrennt von einer Qualitätsfreigabe der Probe.",
            className="note",
        ),
        html.Div([
            html.Button("Ausgewähltes Ergebnis freigeben", id="qc-release", className="primary"),
            html.Div(id="qc-message", className="message"),
        ], className="action-row"),
        html.H3("Prüfung erforderlich"),
        review_table,
        html.H3("Automatische Probenbewertung (Demo; keine Produktfreigabe)"),
        html.P(
            "OOS-Ergebnisse werden unabhängig vom Freigabestatus als untersuchungsbedürftig "
            "markiert. Konformität wird nur angezeigt, wenn alle beauftragten Analysen "
            "freigegeben und gültig sind und keine ausgelassene Pflichtanalyse protokolliert ist.",
            className="note",
        ),
        dash_table.DataTable(
            sample_quality.to_dict("records"),
            [{"name": label, "id": column} for column, label in (
                ("sample_id", "Probe"),
                ("product", "Produkt"),
                ("sample_type", "Probenart"),
                ("batch_id", "Charge"),
                ("analysis_count", "Aufträge"),
                ("required_count", "Pflichtaufträge"),
                ("released_count", "Freigegeben"),
                ("oos_count", "OOS-Werte"),
                ("oos_open_case_count", "Untersuchung offen/fehlend"),
                ("oos_closed_case_count", "Untersuchung abgeschlossen"),
                ("assessment", "Automatische Bewertung (Demo)"),
            )],
            id="qc-sample-assessment",
            page_size=12,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
        ),
        html.H3("OOS-Untersuchungsfälle (Demo)"),
        html.P(
            "Fallabschluss dokumentiert Ursache, Maßnahme und Begründung. Er ändert weder "
            "den OOS-Status des Messwerts noch gibt Probe oder Charge frei.",
            className="note",
        ),
        html.Div([
            dcc.Dropdown(
                oos_result_options,
                id="oos-result-id",
                placeholder="OOS-Ergebnisversion auswählen",
                clearable=True,
            ),
            dcc.Textarea(
                id="oos-initial-description",
                placeholder="Erstbeschreibung / unmittelbare Eindämmung (erforderlich)",
            ),
            html.Button("OOS-Fall eröffnen", id="oos-case-open", className="primary"),
        ], className="sample-form"),
        dash_table.DataTable(
            oos_case_records(repo),
            [
                {"name": label, "id": column}
                for label, column in zip(OOS_CASE_LABELS, OOS_CASE_COLUMNS)
            ],
            id="oos-case-list",
            row_selectable="single",
            page_size=8,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
        ),
        html.Div([
            dcc.Textarea(id="oos-root-cause", placeholder="Ursachenbewertung (erforderlich)"),
            dcc.Textarea(id="oos-corrective-action", placeholder="Korrektur-/Vorbeugemaßnahme (erforderlich)"),
            dcc.Textarea(id="oos-closure-rationale", placeholder="Begründung für den Fallabschluss (erforderlich)"),
            html.Button("OOS-Fall dokumentiert abschließen", id="oos-case-close", className="secondary"),
            html.Div(id="oos-case-message", className="message"),
        ], className="sample-form"),
        html.Div([
            kpi("Maßgebliche Ergebnisse", str(total)),
            kpi("PASS", str(int(counts.get("PASS", 0)))),
            kpi("GRENZNAH", str(int(counts.get("GRENZNAH", 0)))),
            kpi("OOS", str(oos)),
            kpi("OOS-Anteil maßgeblicher Ergebnisse", f"{(100 * oos / total if total else 0):.1f}%"),
        ], className="kpi-grid"),
        dcc.Graph(figure=fig),
        html.H3("Mess- und Ergebnisversionen (Historie)"),
        details,
    ])
