import pkgutil

if not hasattr(pkgutil, "find_loader"):
    def _compat_find_loader(name):
        return pkgutil.get_loader(name)
    pkgutil.find_loader = _compat_find_loader

from datetime import datetime, timedelta
import os
import secrets

from dash import Dash, Input, Output, State, ctx, dcc, html, no_update
from flask import session
from data.repository import Repository
from data.master_data import PLANS
from pages import operations, quality, statistics
from config import APP_TITLE
from services.auth_service import authenticate
from services.workflow_service import WorkflowService
from domain.enums import TaskStatus

repo = Repository()
app = Dash(__name__, title=APP_TITLE, suppress_callback_exceptions=True)
workflow = WorkflowService(repo)
app.server.config.update(
    SECRET_KEY=os.environ.get("CHEMLAB_SESSION_SECRET") or secrets.token_urlsafe(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

app.layout = html.Div([
    html.Header([
        html.Div([
            html.H1(APP_TITLE),
            html.P("Synthetische Demo-Daten · kein validiertes LIMS- oder GMP-System"),
        ]),
        html.Div("Lokale Anmeldung erforderlich"),
    ]),
    dcc.Store(id="auth-revision", data=0),
    dcc.Interval(id="auth-interval", interval=500, n_intervals=0, max_intervals=1),
    html.Div([
        html.H2("Lokale Anmeldung"),
        html.Label(["Benutzername", dcc.Input(id="auth-username", type="text", autoComplete="username")]),
        html.Label(["Kennwort", dcc.Input(id="auth-password", type="password", autoComplete="current-password")]),
        html.Button("Anmelden", id="auth-login", className="primary"),
        html.Div(id="auth-message", role="status", className="message"),
        html.P("Noch kein Konto? Die Ersteinrichtung erfolgt lokal per CLI; siehe README.", className="note"),
    ], id="auth-login-panel"),
    html.Div([
        html.Div([
            html.Span(id="auth-status"),
            html.Button("Abmelden", id="auth-logout", className="secondary"),
        ], className="auth-toolbar"),
        dcc.Tabs(id="tabs", value="operations", children=[
            dcc.Tab(label="Laboratory Operations", value="operations"),
            dcc.Tab(label="Quality Control", value="quality"),
            dcc.Tab(label="Statistics", value="statistics"),
        ]),
        html.Main(id="page", className="content"),
    ], id="authenticated-app", style={"display": "none"}),
])


def current_user():
    username = session.get("username")
    if not username:
        return None
    user = repo.local_user(username)
    if user is None or not user["active"]:
        session.clear()
        return None
    return user


@app.callback(
    Output("auth-message", "children"),
    Output("auth-revision", "data"),
    Input("auth-login", "n_clicks"),
    Input("auth-logout", "n_clicks"),
    State("auth-username", "value"),
    State("auth-password", "value"),
    State("auth-revision", "data"),
    prevent_initial_call=True,
)
def authenticate_user(login_clicks, logout_clicks, username, password, revision):
    if ctx.triggered_id == "auth-logout":
        session.clear()
        return "Abgemeldet.", (revision or 0) + 1
    if ctx.triggered_id != "auth-login" or not login_clicks:
        return no_update, no_update
    user = authenticate(repo, username or "", password or "")
    if user is None:
        return "Anmeldung fehlgeschlagen. Benutzername oder Kennwort ist nicht korrekt.", no_update
    session.clear()
    session["username"] = user["username"]
    session.permanent = True
    return "Anmeldung erfolgreich.", (revision or 0) + 1


@app.callback(
    Output("auth-login-panel", "style"),
    Output("authenticated-app", "style"),
    Output("auth-status", "children"),
    Input("auth-revision", "data"),
    Input("auth-interval", "n_intervals"),
)
def auth_visibility(revision, intervals):
    _ = revision, intervals
    user = current_user()
    if user is None:
        return {}, {"display": "none"}, "Nicht angemeldet"
    return {"display": "none"}, {}, f"Angemeldet: {user['username']} · Rolle: {user['role']}"


@app.callback(Output("page", "children"), Input("tabs", "value"), Input("auth-revision", "data"))
def page(tab, auth_revision):
    _ = auth_revision
    user = current_user()
    if user is None:
        return html.P("Bitte zuerst lokal anmelden.")
    if tab == "operations":
        return operations.layout(repo, is_admin=user["role"] == "Administrator")
    return {"quality": quality.layout, "statistics": statistics.layout}[tab](repo)


@app.callback(
    Output("stats-method", "options"),
    Output("stats-method", "value"),
    Input("stats-product", "value"),
)
def methods(product):
    if current_user() is None:
        return [], None
    r = statistics.result_view(repo)
    r = r.loc[r.is_current.astype(bool) & r.review_status.astype(str).str.startswith("freigegeben")]
    values = sorted(r.loc[r["product"] == product, "method"].unique())
    return values, values[0] if values else None


@app.callback(
    Output("stats-sample-type", "options"),
    Output("stats-sample-type", "value"),
    Input("stats-product", "value"),
    Input("stats-method", "value"),
)
def sample_types(product, method):
    if current_user() is None:
        return [], None
    r = statistics.result_view(repo)
    r = r.loc[r.is_current.astype(bool) & r.review_status.astype(str).str.startswith("freigegeben")]
    selected = r.loc[(r["product"] == product) & (r.method == method)]
    values = sorted(selected.sample_type.unique())
    return values, values[0] if values else None


@app.callback(
    Output("stats-parameter", "options"),
    Output("stats-parameter", "value"),
    Input("stats-product", "value"),
    Input("stats-method", "value"),
    Input("stats-sample-type", "value"),
)
def params(product, method=None, sample_type=None):
    if current_user() is None:
        return [], None
    r = statistics.result_view(repo)
    r = r.loc[r.is_current.astype(bool) & r.review_status.astype(str).str.startswith("freigegeben")]
    selected = r.loc[r["product"] == product]
    if method:
        selected = selected.loc[selected.method == method]
    if sample_type:
        selected = selected.loc[selected.sample_type == sample_type]
    values = sorted(selected["parameter"].unique())
    return values, values[0] if values else None


@app.callback(
    Output("stats-content", "children"),
    Input("stats-product", "value"),
    Input("stats-method", "value"),
    Input("stats-sample-type", "value"),
    Input("stats-parameter", "value"),
    Input("stats-range", "value"),
    Input("stats-start", "date"),
    Input("stats-end", "date"),
    Input("stats-quality", "value"),
)
def stats(product, method, sample_type, parameter, period, start_date, end_date, quality_status):
    if current_user() is None:
        return html.P("Bitte zuerst lokal anmelden.")
    return statistics.content(
        repo, product, parameter, method, sample_type, period, start_date, end_date, quality_status,
    )


QUEUE_FILTERS = ("open", "progress", "critical", "overdue")


@app.callback(
    Output("queue-filter", "data"),
    *[Input(f"kpi-{key}", "n_clicks") for key in QUEUE_FILTERS],
    Input("queue-show-all", "n_clicks"),
    Input("queue-view", "value"),
    State("queue-filter", "data"),
    prevent_initial_call=True,
)
def select_queue_filter(*args):
    clicked = ctx.triggered_id
    if clicked == "queue-view":
        return args[5]
    if clicked == "queue-show-all":
        return "all"
    if clicked not in {f"kpi-{key}" for key in QUEUE_FILTERS}:
        return no_update
    chosen = clicked.removeprefix("kpi-")
    current = args[-1]
    return "all" if current == chosen else chosen


@app.callback(
    Output("queue", "data"),
    Output("queue", "selected_row_ids"),
    Output("queue", "page_current"),
    Output("queue-filter-label", "children"),
    *[
        output
        for key in QUEUE_FILTERS
        for output in (
            Output(f"kpi-{key}-value", "children"),
            Output(f"kpi-{key}", "className"),
            Output(f"kpi-{key}", "aria-pressed"),
        )
    ],
    Input("queue-filter", "data"),
    Input("queue-revision", "data"),
    Input("queue-search", "value"),
    Input("queue-clock", "n_intervals"),
)
def refresh_queue(active_filter, revision, search, tick):
    if current_user() is None:
        return [[], [], 0, "Bitte anmelden"] + [
            item for _ in QUEUE_FILTERS for item in ("0", "kpi kpi-button", "false")
        ]
    _ = revision, tick
    rows, counts = operations.queue_content(repo, active_filter, search or "")
    label = f"{operations.FILTER_LABELS.get(active_filter, 'Aktive Aufträge')} ({len(rows)})"
    values = [rows, [], 0, label]
    for key in QUEUE_FILTERS:
        active = key == active_filter
        values.extend([
            str(counts[key]),
            "kpi kpi-button active" if active else "kpi kpi-button",
            "true" if active else "false",
        ])
    return values


@app.callback(
    Output("sample-methods", "options"),
    Output("sample-methods", "value"),
    Input("sample-product", "value"),
)
def sample_methods(product_id):
    if current_user() is None:
        return [], []
    method_table = repo.table("methods").set_index("method_id")
    plan = PLANS[product_id]
    options = [
        {
            "label": f"{method_table.loc[method_id, 'method']} — "
                     f"{method_table.loc[method_id, 'parameter']} "
                     f"({method_table.loc[method_id, 'unit']}) · Pflicht (Demo)",
            "value": method_id,
        }
        for method_id, _, _, _, _ in plan
    ]
    return options, [method_id for method_id, *_ in plan]


@app.callback(
    Output("sample-message", "children"),
    Output("queue-revision", "data", allow_duplicate=True),
    Output("sample-submission-key", "data"),
    Input("sample-create", "n_clicks"),
    State("sample-product", "value"),
    State("sample-type", "value"),
    State("sample-batch", "value"),
    State("sample-name", "value"),
    State("sample-received", "value"),
    State("sample-order-type", "value"),
    State("sample-methods", "value"),
    State("sample-omission-reason", "value"),
    State("sample-notes", "value"),
    State("sample-submission-key", "data"),
    State("queue-revision", "data"),
    prevent_initial_call=True,
)
def create_sample(
    clicks, product_id, sample_type, batch_id, sample_name, received_at,
    order_type, selected_methods, omission_reason, notes, submission_key, revision,
):
    if not clicks:
        return no_update, no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update, submission_key
    try:
        when = datetime.fromisoformat(received_at) if received_at else None
        actor = user["username"]
        sample_id, task_ids = workflow.create_sample(
            product_id=product_id,
            sample_type=sample_type,
            methods=selected_methods or [],
            received_at=when,
            batch_id=batch_id,
            sample_name=sample_name,
            notes=notes,
            order_type=order_type,
            actor=actor,
            actor_role=user["role"],
            omission_reason=omission_reason,
            submission_key=submission_key,
        )
        message = f"Probe {sample_id} angelegt; {len(task_ids)} getrennte Analyseaufträge: {', '.join(task_ids)}."
        return message, (revision or 0) + 1, __import__("uuid").uuid4().hex
    except (ValueError, TypeError) as exc:
        return f"Keine Änderung: {exc}", no_update, submission_key


@app.callback(
    Output("local-user-message", "children"),
    Output("local-user-list", "data"),
    Input("local-user-create", "n_clicks"),
    State("local-user-name", "value"),
    State("local-user-password", "value"),
    State("local-user-role", "value"),
    State("local-user-employee", "value"),
    prevent_initial_call=True,
)
def create_local_user(clicks, username, password, role, employee_id):
    if not clicks:
        return no_update, no_update
    user = current_user()
    if user is None or user["role"] != "Administrator":
        return "Keine Änderung: Nur Administratoren dürfen lokale Konten verwalten.", no_update
    try:
        from services.auth_service import add_user
        add_user(repo, username or "", password or "", role, employee_id or None, user["username"])
        return f"Konto '{username.strip()}' angelegt.", repo.local_users()
    except ValueError as exc:
        return f"Keine Änderung: {exc}", no_update


@app.callback(
    Output("workflow-message", "children"),
    Output("queue-revision", "data", allow_duplicate=True),
    Input("claim", "n_clicks"),
    Input("start", "n_clicks"),
    Input("review", "n_clicks"),
    Input("release", "n_clicks"),
    Input("record", "n_clicks"),
    State("queue", "selected_row_ids"),
    State("result-value", "value"),
    State("result-comment", "value"),
    State("queue-revision", "data"),
    prevent_initial_call=True,
)
def apply_action(claim_clicks, start_clicks, review_clicks, release_clicks, record_clicks,
                 selected_ids, value, comment, revision):
    action = ctx.triggered_id
    clicks_by_action = {
        "claim": claim_clicks,
        "start": start_clicks,
        "review": review_clicks,
        "release": release_clicks,
        "record": record_clicks,
    }
    if not clicks_by_action.get(action):
        return no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update
    if not selected_ids:
        return "Bitte zuerst genau einen Analyseauftrag auswählen.", no_update
    task_id = selected_ids[0]
    employee_id = user["employee_id"]
    actor = user["username"]
    try:
        if action == "claim":
            workflow.transition(task_id, TaskStatus.CLAIMED.value, employee_id, actor=actor, actor_role=user["role"])
        elif action == "start":
            workflow.transition(task_id, TaskStatus.IN_PROGRESS.value, employee_id, actor=actor, actor_role=user["role"])
        elif action == "review":
            workflow.transition(task_id, TaskStatus.REVIEW_REQUIRED.value, employee_id, actor=actor, actor_role=user["role"])
        elif action == "release":
            workflow.transition(task_id, TaskStatus.RELEASED.value, actor=actor, actor_role=user["role"])
        elif action == "record":
            if value is None:
                raise ValueError("Für die Messung ist ein Messwert erforderlich.")
            workflow.record_result(task_id, value, comment or "", actor=actor, actor_employee_id=employee_id, actor_role=user["role"])
        else:
            return no_update, no_update
        message = f"{task_id}: Aktion erfolgreich ausgeführt (Demo)."
    except ValueError as exc:
        message = f"Keine Änderung: {exc}"
    return message, (revision or 0) + 1


@app.callback(
    Output("qc-message", "children"),
    Output("queue-revision", "data", allow_duplicate=True),
    Input("qc-release", "n_clicks"),
    State("qc-review-list", "selected_row_ids"),
    State("queue-revision", "data"),
    prevent_initial_call=True,
)
def release_quality_result(clicks, selected_ids, revision):
    if not clicks:
        return no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update
    if not selected_ids:
        return "Bitte zuerst einen prüfpflichtigen Analyseauftrag auswählen.", no_update
    try:
        workflow.transition(
            selected_ids[0],
            TaskStatus.RELEASED.value,
            actor=user["username"],
            actor_role=user["role"],
        )
        return f"{selected_ids[0]}: Ergebnisversion fachlich freigegeben (Demo).", (revision or 0) + 1
    except ValueError as exc:
        return f"Keine Änderung: {exc}", (revision or 0) + 1


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
