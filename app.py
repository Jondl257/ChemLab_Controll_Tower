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
import pandas as pd
from data.repository import Repository
from pages import operations, quality, statistics
from config import APP_TITLE
from services.auth_service import authenticate
from services.workflow_service import WorkflowService
from domain.enums import TaskStatus
from services.analytics_service import sample_quality_view

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
        return operations.layout(
            repo,
            is_admin=user["role"] == "Administrator",
            can_edit_samples=user["role"] == "Laborleitung",
        )
    return {"quality": quality.layout, "statistics": statistics.layout}[tab](repo)


@app.callback(
    Output("sample-detail-content", "children"),
    Output("sample-edit-name", "value"),
    Output("sample-edit-batch", "value"),
    Output("sample-edit-notes", "value"),
    Output("sample-edit-type", "value"),
    Input("sample-detail-id", "data"),
    Input("sample-detail-revision", "data"),
)
def sample_detail(sample_id, revision):
    _ = revision
    if current_user() is None:
        return html.P("Bitte zuerst lokal anmelden."), None, None, None, None
    if not sample_id:
        return html.P("Keine Probe ausgewählt."), None, None, None, None
    sample = repo.table("samples")
    selected = sample.loc[sample.sample_id == sample_id]
    if len(selected) != 1:
        return html.P("Probe nicht gefunden."), None, None, None, None
    row = selected.iloc[0]
    return (
        operations.sample_detail_content(repo, sample_id),
        row.sample_name if pd.notna(row.sample_name) else "",
        row.batch_id if pd.notna(row.batch_id) else "",
        row.notes if pd.notna(row.notes) else "",
        row.sample_type,
    )


@app.callback(
    Output("sample-detail-id", "data"),
    Input("queue", "selected_row_ids"),
    Input("queue", "active_cell"),
    State("queue", "data"),
    prevent_initial_call=True,
)
def select_sample_from_queue(selected_task_ids, active_cell, queue_rows):
    if current_user() is None:
        return no_update
    if "queue.active_cell" in ctx.triggered_prop_ids:
        task_id = (active_cell or {}).get("row_id")
        if not task_id or task_id not in {
            row.get("id") for row in queue_rows or []
        }:
            return no_update
    elif len(selected_task_ids or []) == 1:
        task_id = selected_task_ids[0]
    else:
        return no_update
    if not task_id:
        return no_update
    tasks = repo.table("tasks")
    selected = tasks.loc[tasks.task_id == task_id]
    if len(selected) != 1:
        return no_update
    return selected.iloc[0].sample_id


@app.callback(
    Output("sample-detail-modal", "style"),
    Input("sample-detail-id", "data"),
)
def show_sample_detail_modal(sample_id):
    if current_user() is None or not sample_id:
        return {"display": "none"}
    return {"display": "flex"}


@app.callback(
    Output("sample-detail-id", "data", allow_duplicate=True),
    Output("queue", "selected_row_ids", allow_duplicate=True),
    Output("queue", "active_cell", allow_duplicate=True),
    Input("sample-detail-close", "n_clicks"),
    prevent_initial_call=True,
)
def close_sample_detail_modal(clicks):
    if not clicks:
        return no_update, no_update, no_update
    return None, [], None


@app.callback(
    Output("sample-edit-message", "children"),
    Output("sample-detail-revision", "data"),
    Input("sample-edit-save", "n_clicks"),
    State("sample-detail-id", "data"),
    State("sample-edit-name", "value"),
    State("sample-edit-batch", "value"),
    State("sample-edit-notes", "value"),
    State("sample-edit-type", "value"),
    State("sample-edit-reason", "value"),
    State("sample-detail-revision", "data"),
    prevent_initial_call=True,
)
def update_sample_details(
    clicks, sample_id, sample_name, batch_id, notes, sample_type, reason, revision
):
    if not clicks:
        return no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update
    try:
        workflow.update_sample_details(
            sample_id or "",
            sample_name=sample_name,
            batch_id=batch_id,
            notes=notes,
            sample_type=sample_type,
            reason=reason or "",
            actor=user["username"],
            actor_role=user["role"],
        )
        return "Probendaten gespeichert; Änderung und Begründung wurden protokolliert.", (revision or 0) + 1
    except ValueError as exc:
        return f"Keine Änderung: {exc}", no_update


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
    plan = repo.table("specifications")
    plan = plan.loc[
        plan.product_id.eq(product_id) & plan.active.astype(bool)
    ]
    if plan.empty:
        return [], []
    options = [
        {
            "label": f"{method_table.loc[method_id, 'method']} — "
                     f"{method_table.loc[method_id, 'parameter']} "
                     f"({method_table.loc[method_id, 'unit']}) · "
                     f"{'Pflicht' if required else 'Zusatz'} (Demo)",
            "value": method_id,
        }
        for method_id, required in zip(plan.method_id, plan.is_required)
    ]
    return options, plan.method_id.tolist()


@app.callback(
    Output("spec-method", "options"),
    Output("spec-method", "value"),
    Input("spec-product", "value"),
)
def specification_methods(product_id):
    if current_user() is None or not product_id:
        return [], None
    active = repo.table("specifications")
    active = active.loc[
        active.product_id.eq(product_id) & active.active.astype(bool)
    ]
    methods = repo.table("methods").set_index("method_id")
    options = [
        {
            "label": f"{methods.loc[row.method_id, 'method']} · "
                     f"{methods.loc[row.method_id, 'parameter']} ({methods.loc[row.method_id, 'unit']})",
            "value": row.method_id,
        }
        for row in active.itertuples()
    ]
    return options, options[0]["value"] if options else None


@app.callback(
    Output("spec-message", "children"),
    Output("active-specification-table", "children"),
    Input("spec-create", "n_clicks"),
    State("spec-product", "value"),
    State("spec-method", "value"),
    State("spec-target", "value"),
    State("spec-lsl", "value"),
    State("spec-usl", "value"),
    State("spec-sigma", "value"),
    State("spec-reason", "value"),
    prevent_initial_call=True,
)
def create_specification_version(
    clicks, product_id, method_id, target, lsl, usl, sigma, reason
):
    if not clicks:
        return no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update
    try:
        version = workflow.create_specification_version(
            product_id or "",
            method_id or "",
            target=target,
            lsl=lsl,
            usl=usl,
            sigma=sigma,
            reason=reason or "",
            actor=user["username"],
            actor_role=user["role"],
        )
    except ValueError as exc:
        return f"Keine neue Version: {exc}", operations.active_specification_content(repo)
    return (
        f"{version} wurde aktiviert. Bestehende Proben und Aufträge bleiben unverändert.",
        operations.active_specification_content(repo),
    )


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
    Input("local-user-reset", "n_clicks"),
    Input("local-user-deactivate", "n_clicks"),
    Input("local-user-activate", "n_clicks"),
    State("local-user-name", "value"),
    State("local-user-password", "value"),
    State("local-user-role", "value"),
    State("local-user-employee", "value"),
    State("local-user-list", "selected_row_ids"),
    State("local-user-reset-password", "value"),
    prevent_initial_call=True,
)
def manage_local_users(
    create_clicks,
    reset_clicks,
    deactivate_clicks,
    activate_clicks,
    username,
    password,
    role,
    employee_id,
    selected_ids,
    reset_password_value,
):
    clicks_by_action = {
        "local-user-create": create_clicks,
        "local-user-reset": reset_clicks,
        "local-user-deactivate": deactivate_clicks,
        "local-user-activate": activate_clicks,
    }
    action = ctx.triggered_id
    if not clicks_by_action.get(action):
        return no_update, no_update
    user = current_user()
    if user is None or user["role"] != "Administrator":
        return "Keine Änderung: Nur Administratoren dürfen lokale Konten verwalten.", no_update
    try:
        if action == "local-user-create":
            from services.auth_service import add_user
            add_user(repo, username or "", password or "", role, employee_id or None, user["username"])
            message = f"Konto '{username.strip()}' angelegt."
        else:
            if len(selected_ids or []) != 1:
                raise ValueError("Bitte genau ein lokales Benutzerkonto auswählen.")
            selected_username = selected_ids[0]
            if action == "local-user-reset":
                from services.auth_service import reset_password
                reset_password(
                    repo, selected_username, reset_password_value or "", user["username"]
                )
                message = f"Kennwort für '{selected_username}' zurückgesetzt."
            else:
                active = action == "local-user-activate"
                repo.set_local_user_active(selected_username, active, user["username"])
                state = "aktiviert" if active else "deaktiviert"
                message = f"Konto '{selected_username}' {state}."
        return message, operations.local_user_records(repo)
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
    Input("task-controls-save", "n_clicks"),
    Input("task-reassign", "n_clicks"),
    Input("task-reopen", "n_clicks"),
    State("queue", "selected_row_ids"),
    State("result-value", "value"),
    State("result-comment", "value"),
    State("task-priority", "value"),
    State("task-deadline", "value"),
    State("task-reassign-employee", "value"),
    State("task-change-reason", "value"),
    State("queue-revision", "data"),
    prevent_initial_call=True,
)
def apply_action(claim_clicks, start_clicks, review_clicks, release_clicks, record_clicks,
                 controls_clicks, reassign_clicks, reopen_clicks, selected_ids, value,
                 comment, priority, deadline_value, target_employee, change_reason, revision):
    action = ctx.triggered_id
    clicks_by_action = {
        "claim": claim_clicks,
        "start": start_clicks,
        "review": review_clicks,
        "release": release_clicks,
        "record": record_clicks,
        "task-controls-save": controls_clicks,
        "task-reassign": reassign_clicks,
        "task-reopen": reopen_clicks,
    }
    if not clicks_by_action.get(action):
        return no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update
    if len(selected_ids or []) != 1:
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
        elif action == "task-controls-save":
            parsed_deadline = (
                datetime.fromisoformat(deadline_value) if deadline_value else None
            )
            workflow.update_task_controls(
                task_id,
                actor=actor,
                actor_role=user["role"],
                reason=change_reason or "",
                priority=priority,
                deadline_at=parsed_deadline,
            )
        elif action == "task-reassign":
            workflow.reassign_task(
                task_id,
                target_employee or "",
                actor=actor,
                actor_role=user["role"],
                reason=change_reason or "",
            )
        elif action == "task-reopen":
            workflow.reopen_cancelled_task(
                task_id,
                actor=actor,
                actor_role=user["role"],
                reason=change_reason or "",
            )
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


@app.callback(
    Output("oos-case-message", "children"),
    Output("oos-case-list", "data"),
    Output("qc-sample-assessment", "data"),
    Input("oos-case-open", "n_clicks"),
    Input("oos-case-close", "n_clicks"),
    State("oos-result-id", "value"),
    State("oos-initial-description", "value"),
    State("oos-case-list", "selected_row_ids"),
    State("oos-root-cause", "value"),
    State("oos-corrective-action", "value"),
    State("oos-closure-rationale", "value"),
    prevent_initial_call=True,
)
def manage_oos_case(
    open_clicks,
    close_clicks,
    result_id,
    initial_description,
    selected_case_ids,
    root_cause,
    corrective_action,
    closure_rationale,
):
    action = ctx.triggered_id
    if action == "oos-case-open" and not open_clicks:
        return no_update, no_update, no_update
    if action == "oos-case-close" and not close_clicks:
        return no_update, no_update, no_update
    user = current_user()
    if user is None:
        return "Bitte zuerst lokal anmelden.", no_update, no_update
    if user["role"] != "Laborleitung":
        return "Keine Änderung: Nur die Laborleitung darf OOS-Fälle verwalten.", no_update, no_update
    try:
        if action == "oos-case-open":
            case_id = workflow.open_oos_case(
                result_id or "",
                initial_description or "",
                actor=user["username"],
                actor_role=user["role"],
            )
            message = f"OOS-Fall {case_id} eröffnet."
        elif action == "oos-case-close":
            if len(selected_case_ids or []) != 1:
                raise ValueError("Bitte genau einen OOS-Fall auswählen.")
            workflow.close_oos_case(
                selected_case_ids[0],
                root_cause=root_cause or "",
                corrective_action=corrective_action or "",
                closure_rationale=closure_rationale or "",
                actor=user["username"],
                actor_role=user["role"],
            )
            message = (
                f"OOS-Fall {selected_case_ids[0]} abgeschlossen; "
                "der Ergebnisstatus bleibt OOS."
            )
        else:
            return no_update, no_update, no_update
        return (
            message,
            quality.oos_case_records(repo),
            sample_quality_view(repo).to_dict("records"),
        )
    except ValueError as exc:
        return f"Keine Änderung: {exc}", no_update, no_update


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
