from datetime import date, timedelta

from dash import dcc, html, dash_table
import plotly.graph_objects as go

from components.ui import kpi
from config import COLORS
from services.analytics_service import result_view, statistics


def _released(repo):
    rows = result_view(repo)
    return rows.loc[
        rows.is_current.astype(bool) & rows.review_status.astype(str).str.startswith("freigegeben")
    ]


def _options(rows, column):
    return sorted(rows[column].dropna().unique().tolist()) if not rows.empty else []


def layout(repo):
    results = _released(repo)
    products = _options(results, "product")
    product = products[0] if products else None
    methods = _options(results.loc[results["product"] == product], "method") if product else []
    method = methods[0] if methods else None
    parameters = _options(results.loc[results["method"] == method], "parameter") if method else []
    parameter = parameters[0] if parameters else None
    sample_types = _options(results.loc[results["method"] == method], "sample_type") if method else []
    sample_type = sample_types[0] if sample_types else None
    today = date.today()
    return html.Div([
        html.P("Datenbasis: aktuell maßgebliche fachlich freigegebene Ergebnisse; Messdatum wird für den Zeitraum verwendet.", className="note"),
        html.Div([
            html.Label(["Produkt", dcc.Dropdown(products, product, id="stats-product", clearable=False)]),
            html.Label(["Methode", dcc.Dropdown(methods, method, id="stats-method", clearable=False)]),
            html.Label(["Probenart", dcc.Dropdown(sample_types, sample_type, id="stats-sample-type", clearable=False)]),
            html.Label(["Parameter", dcc.Dropdown(parameters, parameter, id="stats-parameter", clearable=False)]),
            html.Label(["Messzeitraum", dcc.Dropdown(
                [{"label": label, "value": value} for label, value in (
                    ("7 Tage", "7"), ("30 Tage", "30"), ("90 Tage", "90"),
                    ("Gesamter Zeitraum", "all"), ("Benutzerdefiniert", "custom"),
                )],
                "all", id="stats-range", clearable=False,
            )]),
            html.Label(["Von (Messdatum)", dcc.DatePickerSingle(id="stats-start", date=today - timedelta(days=30))]),
            html.Label(["Bis einschließlich (Messdatum)", dcc.DatePickerSingle(id="stats-end", date=today)]),
            html.Label(["Qualitätsstatus", dcc.Dropdown(
                [{"label": value, "value": value} for value in ("Alle", "PASS", "GRENZNAH", "OOS")],
                "Alle", id="stats-quality", clearable=False,
            )]),
        ], className="filters"),
        html.Div(content(repo, product, parameter, method, sample_type), id="stats-content"),
    ])


def content(repo, product, parameter, method=None, sample_type=None, period="all", start_date=None, end_date=None, quality_status=None):
    today = date.today()
    if period in {"7", "30", "90"}:
        end_date = today
        start_date = today - timedelta(days=int(period) - 1)
    elif period == "all":
        start_date = end_date = None
    try:
        rows, summary = statistics(
            repo,
            product=product,
            method=method,
            sample_type=sample_type,
            parameter=parameter,
            start_date=start_date,
            end_date=end_date,
            quality_status=None if quality_status in (None, "Alle") else quality_status,
        )
    except ValueError as exc:
        return html.Div([html.P(str(exc), className="message")])

    def format_value(value):
        return "N/A" if value is None else f"{value:.3f}"

    cards = html.Div([
        kpi("Freigegebene Ergebnisse n", str(summary["n"])),
        kpi("MITTELWERT", format_value(summary["mean"])),
        kpi("MEDIAN", format_value(summary["median"])),
        kpi("STDABW.", format_value(summary["std"])),
        kpi("Cp", format_value(summary["cp"])),
        kpi("Cpk", format_value(summary["cpk"])),
    ], className="kpi-grid")
    if rows.empty:
        return html.Div([cards, html.P("Keine freigegebenen Ergebnisse für diese Auswahl.")])

    rows = rows.sort_values("measured_at").copy()
    color_map = {"PASS": COLORS["pass"], "GRENZNAH": COLORS["near_limit"], "OOS": COLORS["oos"]}
    point_colors = [color_map.get(status, COLORS["neutral"]) for status in rows.quality_status]
    figure = go.Figure()
    figure.add_scatter(
        x=rows.measured_at,
        y=rows.value,
        mode="markers",
        name="Freigegebenes Ergebnis",
        marker={"color": point_colors, "size": 10},
        customdata=rows[["sample_id", "task_id", "quality_status", "result_version"]].to_numpy(),
        hovertemplate=(
            "Messdatum: %{x}<br>Wert: %{y}<br>Probe: %{customdata[0]}<br>"
            "Auftrag: %{customdata[1]}<br>Status: %{customdata[2]}<br>"
            "Ergebnisversion: %{customdata[3]}<extra></extra>"
        ),
    )
    for key, label, symbol, color in (
        ("target", "Sollwert (historische Spezifikation)", "line-ew", "#667085"),
        ("lsl", "Untere Spezifikationsgrenze (historisch)", "triangle-down", COLORS["oos"]),
        ("usl", "Obere Spezifikationsgrenze (historisch)", "triangle-up", COLORS["oos"]),
    ):
        figure.add_scatter(
            x=rows.measured_at, y=rows[key], mode="markers", name=label,
            marker={"symbol": symbol, "color": color, "size": 7},
        )
    figure.update_layout(
        title="Freigegebene Ergebnisse nach Messdatum — rot = OOS, orange = grenznah",
        plot_bgcolor="white", paper_bgcolor="white",
        xaxis_title="Messdatum", yaxis_title=rows.unit.iloc[0],
    )
    columns = ["sample_id", "task_id", "method", "parameter", "value", "unit", "quality_status", "measured_at", "result_version", "specification_version"]
    detail = dash_table.DataTable(
        rows[columns].to_dict("records"),
        [{"name": name, "id": name} for name in columns],
        page_size=10, sort_action="native", filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Arial", "fontSize": 12, "padding": "8px", "textAlign": "left"},
    )
    return html.Div([
        cards,
        dcc.Graph(figure=figure),
        html.P(
            "Cp/Cpk und Kontrollgrenzen werden nur bei mindestens 30 homogenen freigegebenen "
            "Ergebnissen ohne vermischte Methode, Probenart, Einheit oder Spezifikationsgrenze "
            "angezeigt. Das ersetzt keine fachliche Prozessfähigkeitsbewertung.",
            className="note",
        ),
        html.H3("Verwendete Ergebnisversionen"),
        detail,
    ])
