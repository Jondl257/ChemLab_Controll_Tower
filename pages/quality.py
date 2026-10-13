from dash import dcc, html, dash_table
import plotly.express as px

from components.ui import kpi
from config import COLORS
from domain.enums import TaskStatus
from services.analytics_service import result_view


def layout(repo):
    results = result_view(repo)
    current = results.loc[results.is_current.astype(bool)].copy()
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
