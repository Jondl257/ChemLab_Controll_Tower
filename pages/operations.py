from uuid import uuid4

from dash import dcc, html, dash_table
import pandas as pd
import plotly.express as px

from components.ui import kpi
from services.analytics_service import result_view, task_view, queue_records, queue_masks
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
    specifications = repo.table("specifications")
    active_plan = specifications.loc[
        specifications.product_id.eq(first_product)
        & specifications.active.astype(bool)
    ]
    method_options = [
        {
            "label": f"{methods.loc[method_id, 'method']} — {methods.loc[method_id, 'parameter']} "
                     f"({methods.loc[method_id, 'unit']}) · "
                     f"{'Pflicht' if required else 'Zusatz'} (Demo)",
            "value": method_id,
        }
        for method_id, required in zip(active_plan.method_id, active_plan.is_required)
    ]
    product_options = [
        {"label": row.product, "value": row.product_id}
        for row in products.itertuples()
    ]
    version = str(active_plan.version.iloc[0]) if not active_plan.empty else "nicht verfügbar"
    received = __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M")
    return html.Details([
        html.Summary("Neue Probe und mehrere Analyseaufträge anlegen"),
        html.P(
            f"Demo-Regel: aktive Planspezifikation {version} wird beim Anlegen an der Probe "
            "und ihren Analyseaufträgen festgeschrieben. Alle Spezifikationswerte sind synthetisch.",
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


def active_specification_content(repo):
    specifications = repo.table("specifications")
    active = specifications.loc[specifications.active.astype(bool)]
    products = repo.table("products")[["product_id", "product"]]
    methods = repo.table("methods")[["method_id", "method", "parameter", "unit"]]
    active = active.merge(products, on="product_id").merge(methods, on="method_id")
    columns = [
        "product", "version", "method", "parameter", "target", "lsl", "usl",
        "sigma", "is_required",
    ]
    labels = [
        "Produkt", "Aktive Version", "Methode", "Parameter", "Sollwert",
        "Untergrenze", "Obergrenze", "Demo-Streuung", "Pflicht",
    ]
    return dash_table.DataTable(
        active[columns].rename(columns=dict(zip(columns, labels))).fillna("").astype(str).to_dict("records"),
        [{"name": label, "id": label} for label in labels],
        page_size=12,
        sort_action="native",
        style_table={"overflowX": "auto"},
    )


def _specification_version_form(repo):
    products = repo.table("products")
    first_product = products.iloc[0].product_id
    product_options = [
        {"label": row.product, "value": row.product_id}
        for row in products.itertuples()
    ]
    return html.Details([
        html.Summary("Demo-Spezifikation versionieren"),
        html.P(
            "Erstellt eine neue aktive Version durch Kopieren des bestehenden Plans und "
            "Ändern genau einer Methode. Vorhandene Proben/Aufträge behalten ihre Version; "
            "diese Demo-Werte sind nicht fachlich validiert.",
            className="note",
        ),
        html.Div([
            dcc.Dropdown(product_options, first_product, id="spec-product", clearable=False),
            dcc.Dropdown(id="spec-method", placeholder="Methode der aktiven Version", clearable=False),
            dcc.Input(id="spec-target", type="number", placeholder="Sollwert", step="any"),
            dcc.Input(id="spec-lsl", type="number", placeholder="Untergrenze", step="any"),
            dcc.Input(id="spec-usl", type="number", placeholder="Obergrenze", step="any"),
            dcc.Input(id="spec-sigma", type="number", placeholder="Demo-Streuung > 0", min=0, step="any"),
            dcc.Textarea(id="spec-reason", placeholder="Begründung der Demo-Version (erforderlich)"),
            html.Button("Neue Version erstellen", id="spec-create", className="primary"),
            html.Div(id="spec-message", className="message"),
        ], className="sample-form"),
        html.H4("Aktive Demo-Spezifikationen"),
        html.Div(active_specification_content(repo), id="active-specification-table"),
    ])


def local_user_records(repo):
    return [
        {**user, "id": user["username"]}
        for user in repo.local_users()
    ]


def sample_options(repo):
    samples = repo.table("samples").merge(
        repo.table("products")[["product_id", "product"]],
        on="product_id",
    )
    return [
        {
            "label": (
                f"{row.sample_id} · {row.product} · {row.sample_type}"
                f"{f' · {row.batch_id}' if pd.notna(row.batch_id) and row.batch_id else ''}"
            ),
            "value": row.sample_id,
        }
        for row in samples.itertuples()
    ]


def sample_detail_content(repo, sample_id):
    samples = repo.table("samples")
    selected = samples.loc[samples.sample_id == sample_id]
    if len(selected) != 1:
        return html.P("Probe nicht gefunden.")
    sample = selected.iloc[0]
    tasks = task_view(repo)
    tasks = tasks.loc[tasks.sample_id == sample_id]
    task_columns = [
        "task_id", "method", "specification_version", "status", "priority",
        "deadline", "employee",
    ]
    task_labels = [
        "Auftrag", "Methode", "Spezifikationsversion", "Status", "Priorität",
        "Fälligkeit", "Bearbeiter",
    ]
    task_records = tasks[task_columns].fillna("").astype(str).to_dict("records")
    task_table = dash_table.DataTable(
        task_records,
        [{"name": label, "id": column} for label, column in zip(task_labels, task_columns)],
        page_size=8,
        sort_action="native",
        style_table={"overflowX": "auto"},
    )

    results = result_view(repo)
    results = results.loc[results.sample_id == sample_id].sort_values(
        ["task_id", "result_version"]
    )
    result_columns = [
        "task_id", "parameter", "value", "unit", "quality_status",
        "result_version", "is_current", "review_status", "measured_at",
        "released_at", "specification_version", "recorded_by", "released_by", "comment",
    ]
    result_labels = [
        "Auftrag", "Parameter", "Messwert", "Einheit", "QC-Status",
        "Version", "Maßgeblich", "Prüfstatus", "Gemessen", "Freigegeben",
        "Spezifikationsversion", "Erfasst von", "Freigegeben von", "Kommentar",
    ]
    result_table = dash_table.DataTable(
        results[result_columns].fillna("").astype(str).to_dict("records"),
        [{"name": label, "id": column} for label, column in zip(result_labels, result_columns)],
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
    )

    events = repo.events(sample_id)
    for task_id in tasks.task_id:
        events.extend(repo.events(task_id))
    events.sort(key=lambda event: (event["occurred_at"], event["event_id"]))
    event_columns = ["occurred_at", "entity_type", "entity_id", "action", "actor", "old_value", "new_value", "reason"]
    event_labels = ["Zeitpunkt", "Typ", "ID", "Aktion", "Akteur", "Vorher", "Nachher", "Begründung"]
    event_table = dash_table.DataTable(
        [{column: str(event.get(column) or "") for column in event_columns} for event in events],
        [{"name": label, "id": column} for label, column in zip(event_labels, event_columns)],
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
    )
    product = repo.table("products").set_index("product_id").loc[sample.product_id, "product"]
    return html.Div([
        html.P(
            f"Probe {sample.sample_id} · {product} · {sample.sample_type} · "
            f"Eingang: {sample.received_at} · "
            f"Spezifikation: {sample.specification_version} · Angelegt von: {sample.created_by}"
        ),
        html.H4("Analyseaufträge"),
        task_table,
        html.H4("Messungen und Ergebnisversionen"),
        result_table,
        html.H4("Änderungs- und Workflowhistorie"),
        event_table,
    ])


def layout(repo, is_admin=False, can_edit_samples=False):
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
        style_data={"cursor": "pointer"},
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
        html.P(
            "Eine Queue-Zeile anklicken oder ihren Auswahlkreis verwenden, um die zugehörige Probe im Popup anzusehen.",
            className="note",
        ),
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
        dcc.Store(id="sample-detail-id", data=None),
        dcc.Store(id="sample-detail-dismissed", data=False),
        html.Div([
            html.Div([
                html.Div([
                    html.H2("Probendetails", id="sample-detail-title"),
                    html.Button(
                        "Schließen",
                        id="sample-detail-close",
                        className="secondary",
                        **{"aria-label": "Probendetails schließen"},
                    ),
                ], className="sample-modal-header"),
            html.Div(id="sample-detail-content"),
            html.H4("Stammdaten ändern"),
            html.Div([
                dcc.Input(id="sample-edit-name", type="text", placeholder="Probenbezeichnung", disabled=not can_edit_samples),
                dcc.Input(id="sample-edit-batch", type="text", placeholder="Charge", disabled=not can_edit_samples),
                dcc.Textarea(id="sample-edit-notes", placeholder="Notiz", disabled=not can_edit_samples),
                dcc.Dropdown(
                    [{"label": value, "value": value} for value in SAMPLE_TYPES],
                    id="sample-edit-type",
                    clearable=False,
                    placeholder="Probenart",
                    disabled=not can_edit_samples,
                ),
                dcc.Textarea(
                    id="sample-edit-reason",
                    placeholder="Begründung (erforderlich)",
                    disabled=not can_edit_samples,
                ),
                html.Button(
                    "Probendaten speichern",
                    id="sample-edit-save",
                    className="primary",
                    disabled=not can_edit_samples,
                ),
            ], className="sample-form"),
            html.Div(id="sample-edit-message", className="message"),
            dcc.Store(id="sample-detail-revision", data=0),
            ], className="sample-modal-panel", role="dialog", **{"aria-modal": "true"}),
        ], id="sample-detail-modal", className="sample-modal", style={"display": "none"}),
        *admin_panel,
        *([_specification_version_form(repo)] if can_edit_samples else []),
    ])
