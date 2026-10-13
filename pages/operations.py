from uuid import uuid4

from dash import dcc, html, dash_table
import plotly.express as px

from components.ui import kpi
from data.master_data import PLANS
from services.analytics_service import task_view, queue_records, queue_masks
from services.workflow_service import SAMPLE_TYPES

QUEUE_COLUMNS = [
    "priority",
    "deadline_status",
    "task_id",
    "sample_id",
    "product",
    "sample_type",
    "method",
    "employee",
    "status",
    "deadline",
    "instrument_id",
    "batch_id",
    "product_class",
]
QUEUE_LABELS = {
    "priority": "Priorität",
    "deadline_status": "Friststatus",
    "task_id": "Auftrag",
    "sample_id": "Probe",
    "product": "Produkt",
    "sample_type": "Probenart",
    "method": "Methode",
    "employee": "Bearbeiter",
    "status": "Bearbeitungsstatus",
    "deadline": "Fälligkeit",
    "instrument_id": "Gerät",
    "batch_id": "Charge",
    "product_class": "Produktklasse",
}
FILTER_LABELS = {
    "all": "Aktive Aufträge",
    "open": "Offene Aufträge (alle aktiven Status)",
    "overdue": "Überfällige Aufträge",
    "progress": "In Bearbeitung",
    "completed": "Heute freigegeben",
    "critical": "Kritische Aufträge",
    "review": "Prüfung erforderlich",
}


def queue_content(repo, active_filter="all", search=""):
    tasks = task_view(repo)
    masks = queue_masks(tasks)
    mask = tasks.status.notna() if active_filter == "history" else masks.get(active_filter, masks["active"])
    query = (search or "").strip().casefold()
    if query:
        search_mask = tasks[["task_id", "sample_id", "product", "batch_id"]].fillna("").astype(str).apply(
            lambda column: column.str.casefold().str.contains(query, regex=False)
        ).any(axis=1)
        matched_sample_ids = set(tasks.loc[search_mask, "sample_id"])
        if matched_sample_ids:
            search_mask = search_mask | tasks.sample_id.isin(matched_sample_ids)
            filtered = tasks.loc[search_mask].copy()
        else:
            filtered = tasks.loc[mask & search_mask].copy()
    else:
        filtered = tasks.loc[mask].copy()
    columns = [column for column in QUEUE_COLUMNS if column in filtered]
    return queue_records(filtered[columns]), {key: int(value.sum()) for key, value in masks.items()}


def _sample_form(repo):
    products = repo.table("products")
    first_product = products.iloc[0].product_id
    methods = repo.table("methods").set_index("method_id")
    method_options = [
        {
            "label": f"{methods.loc[method_id, 'method']} — {methods.loc[method_id, 'parameter']} "
                     f"({methods.loc[method_id, 'unit']}) · Pflicht (Demo)"
                     if required else
                     f"{methods.loc[method_id, 'method']} — {methods.loc[method_id, 'parameter']} "
                     f"({methods.loc[method_id, 'unit']}) · Zusatz",
            "value": method_id,
        }
        for method_id, _, _, _, _ in PLANS[first_product]
        for required in (True,)
    ]
    product_options = [
        {"label": row.product, "value": row.product_id}
        for row in products.itertuples()
    ]
    received = __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M")
    return html.Details([
        html.Summary("Neue Probe und mehrere Analyseaufträge anlegen"),
        html.P(
            "Demo-Regel: Produktbasisplan vorausgewählt; bestehende Spezifikationen sind "
            "synthetisch. Die Berechtigung für die Anlage wird aus dem lokalen Benutzerkonto geprüft.",
            className="note",
        ),
        html.Div([
            html.Label(["Produkt", dcc.Dropdown(product_options, first_product, id="sample-product", clearable=False)]),
            html.Label(["Probenart", dcc.Dropdown(
                [{"label": value, "value": value} for value in SAMPLE_TYPES],
                SAMPLE_TYPES[0], id="sample-type", clearable=False,
            )]),
            html.Label(["Charge (optional)", dcc.Input(id="sample-batch", type="text", placeholder="Leer lassen, falls unbekannt")]),
            html.Label(["Probenbezeichnung (optional)", dcc.Input(id="sample-name", type="text")]),
            html.Label(["Probeneingang", dcc.Input(id="sample-received", type="datetime-local", value=received)]),
            html.Label(["Auftragsart (Demo-SLA)", dcc.Dropdown(
                [{"label": item, "value": item} for item in ("Routine", "Produktion dringend", "Stabilitätsprobe")],
                "Routine", id="sample-order-type", clearable=False,
            )]),
            html.Label(["Methoden (Pflichtumfang vorläufig Demo)", dcc.Checklist(
                method_options,
                [option["value"] for option in method_options],
                id="sample-methods",
            )]),
            html.Label(["Begründung für abgewählte Pflichtanalysen", dcc.Input(id="sample-omission-reason", type="text")]),
            html.Label(["Bemerkung", dcc.Textarea(id="sample-notes")]),
            html.Button("Probe und Aufträge speichern", id="sample-create", className="primary"),
            html.Div(id="sample-message", className="message"),
            dcc.Store(id="sample-submission-key", data=str(uuid4())),
        ], className="sample-form"),
    ])


def local_user_records(repo):
    return [
        {**user, "id": user["username"]}
        for user in repo.local_users()
    ]


def layout(repo, is_admin=False):
    tasks = task_view(repo)
    masks = queue_masks(tasks)
    active = masks["active"]
    chart = px.bar(
        tasks[active].groupby("priority").size().reset_index(name="Anzahl"),
        x="priority", y="Anzahl", color="priority",
        color_discrete_map={"Normal": "#667085", "Hoch": "#B06D00", "Kritisch": "#B42318"},
        title="Aktive Aufträge nach wirksamer Priorität",
    )
    table_data, _ = queue_content(repo)
    table_columns = [{"name": QUEUE_LABELS[column], "id": column} for column in QUEUE_COLUMNS]
    table = dash_table.DataTable(
        table_data,
        table_columns,
        id="queue",
        page_size=12,
        sort_action="native",
        filter_action="native",
        row_selectable="single",
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "Arial", "fontSize": 12, "padding": "8px", "textAlign": "left"},
        hidden_columns=["instrument_id", "batch_id", "product_class"],
    )
    cards = [
        kpi("OFFEN", str(masks["open"].sum()), "Alle aktiven Aufträge, einschließlich Prüfbedarf", button_id="kpi-open"),
        kpi("IN BEARBEITUNG", str(masks["progress"].sum()), "Aktive Aufträge", button_id="kpi-progress"),
        kpi("KRITISCH", str(masks["critical"].sum()), "Teilmenge aktiver Aufträge", button_id="kpi-critical"),
        kpi("ÜBERFÄLLIG", str(masks["overdue"].sum()), "Friststatus, unabhängig von Priorität", button_id="kpi-overdue"),
    ]
    controls = html.Details([
        html.Summary("Ausgewählten Auftrag bearbeiten"),
        html.P("Aktionen werden serverseitig anhand des lokalen Kontos und seiner Rolle geprüft.", className="note"),
        html.Div([
            html.Span("Angemeldete lokale Identität"),
            html.Button("Übernehmen", id="claim", className="primary"),
            html.Button("Starten", id="start", className="primary"),
            html.Button("Prüfung anfordern", id="review", className="secondary"),
            html.Button("Freigeben", id="release", className="secondary"),
        ], className="action-row"),
        html.Div([
            dcc.Input(id="result-value", type="number", placeholder="Messwert"),
            dcc.Input(id="result-comment", type="text", placeholder="Kommentar"),
            html.Button("Messung erfassen", id="record", className="primary"),
        ], className="action-row"),
        html.H4("Beaufsichtigte Auftragsänderungen (Laborleitung)"),
        html.Div([
            dcc.Dropdown(
                [
                    {"label": "Normal", "value": "Normal"},
                    {"label": "Hoch", "value": "Hoch"},
                    {"label": "Kritisch", "value": "Kritisch"},
                    {"label": "Systemvorschlag übernehmen", "value": "Systemvorschlag"},
                ],
                id="task-priority",
                placeholder="Priorität unverändert",
                clearable=True,
            ),
            dcc.Input(
                id="task-deadline",
                type="datetime-local",
                placeholder="Neue Fälligkeit",
            ),
            html.Button("Priorität/Frist ändern", id="task-controls-save", className="secondary"),
        ], className="action-row"),
        html.Div([
            dcc.Dropdown(
                [
                    {"label": f"{row.employee} ({row.employee_id})", "value": row.employee_id}
                    for row in repo.table("employees").itertuples()
                    if row.role == "Laborant"
                ],
                id="task-reassign-employee",
                placeholder="Ziel-Laborant",
                clearable=True,
            ),
            html.Button("Neu zuweisen", id="task-reassign", className="secondary"),
            html.Button("Abgebrochenen Auftrag wiedereröffnen", id="task-reopen", className="secondary"),
        ], className="action-row"),
        dcc.Textarea(
            id="task-change-reason",
            placeholder="Begründung für Änderung, Neuzuweisung oder Wiedereröffnung (erforderlich)",
        ),
        html.Div(id="workflow-message", className="message"),
    ])
    admin_panel = []
    if is_admin:
        employees = repo.table("employees")
        admin_panel = [html.Details([
            html.Summary("Lokale Benutzer verwalten (Administrator)"),
            html.P("Kennwörter werden gehasht gespeichert. Konten sind lokal; keine Unternehmensanmeldung.", className="note"),
            dcc.Input(id="local-user-name", type="text", placeholder="Benutzername"),
            dcc.Input(id="local-user-password", type="password", placeholder="Kennwort (mindestens 12 Zeichen)"),
            dcc.Dropdown(
                [{"label": role, "value": role} for role in ("Laborant", "Laborleitung", "Administrator")],
                "Laborant", id="local-user-role", clearable=False,
            ),
            dcc.Dropdown(
                [{"label": "Kein Mitarbeiterbezug", "value": ""}] + [
                    {"label": f"{row.employee} ({row.employee_id}, {row.role})", "value": row.employee_id}
                    for row in employees.itertuples()
                ],
                "E-01", id="local-user-employee", clearable=True,
            ),
            html.Button("Lokales Konto anlegen", id="local-user-create", className="primary"),
            html.Div([
                dcc.Input(
                    id="local-user-reset-password",
                    type="password",
                    placeholder="Neues Kennwort (mindestens 12 Zeichen)",
                ),
                html.Button("Kennwort zurücksetzen", id="local-user-reset", className="secondary"),
                html.Button("Konto deaktivieren", id="local-user-deactivate", className="secondary"),
                html.Button("Konto aktivieren", id="local-user-activate", className="secondary"),
            ], className="action-row"),
            html.P(
                "Für Kontoaktionen zuerst genau einen Eintrag auswählen. Das letzte aktive "
                "Administratorkonto kann nicht deaktiviert werden.",
                className="note",
            ),
            html.Div(id="local-user-message", className="message"),
            dash_table.DataTable(
                local_user_records(repo),
                [{"name": label, "id": column} for column, label in (
                    ("username", "Benutzer"), ("role", "Rolle"), ("employee_id", "Mitarbeiter"),
                    ("active", "Aktiv"), ("created_at", "Angelegt"), ("created_by", "Erstellt von"),
                )],
                id="local-user-list",
                row_selectable="single",
                page_size=10,
            ),
        ])]
    return html.Div([
        dcc.Store(id="queue-filter", data="all"),
        dcc.Store(id="queue-revision", data=0),
        dcc.Interval(id="queue-clock", interval=60_000, n_intervals=0),
        html.Div(cards, className="kpi-grid"),
        dcc.Graph(figure=chart),
        html.H3("Analyse-Queue"),
        html.Div([
            html.Span("Aktive Aufträge", id="queue-filter-label"),
            dcc.Input(id="queue-search", type="search", placeholder="Auftrag, Probe, Produkt oder Charge suchen"),
            dcc.Dropdown(
                [
                    {"label": "Alle aktiven Aufträge", "value": "all"},
                    {"label": "Prüfung erforderlich", "value": "review"},
                    {"label": "Heute freigegeben", "value": "completed"},
                    {"label": "Abgebrochene Aufträge", "value": "cancelled"},
                    {"label": "Alle historischen Aufträge", "value": "history"},
                ],
                "all", id="queue-view", clearable=False, style={"maxWidth": "320px"},
            ),
            html.Button("Ansicht zurücksetzen", id="queue-show-all", n_clicks=0, type="button"),
        ], className="queue-filter-bar"),
        html.P("KPI-Zahlen beziehen sich auf den Gesamtbestand und überschneiden sich. Suche/Filter der Tabelle gelten zusätzlich."),
        table,
        controls,
        _sample_form(repo),
        *admin_panel,
    ])
