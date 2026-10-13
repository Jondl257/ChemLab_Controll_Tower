from datetime import datetime, timedelta

import pytest
from dash import dcc

import app as dashboard
from app import app
from data.generator import generate_demo_data
from data.master_data import PRODUCTS
from data.repository import Repository
from domain.enums import TaskStatus
from pages.operations import layout as operations_layout
from services.analytics_service import result_view, task_view
from services.auth_service import add_user
from services.workflow_service import WorkflowService

client = app.server.test_client()


@pytest.fixture(autouse=True)
def isolated_logged_in_user(monkeypatch):
    local_repo = Repository(":memory:")
    add_user(local_repo, "lead", "test-password-123", "Laborleitung", "E-06")
    add_user(local_repo, "lab", "test-password-456", "Laborant", "E-01")
    add_user(local_repo, "admin", "test-password-789", "Administrator", None)
    monkeypatch.setattr(dashboard, "repo", local_repo)
    monkeypatch.setattr(dashboard, "workflow", WorkflowService(local_repo))
    with client.session_transaction() as user_session:
        user_session.clear()
        user_session["username"] = "lead"
    yield local_repo
    with client.session_transaction() as user_session:
        user_session.clear()


def callback_request(output, outputs, inputs, state=None, changed=None):
    return client.post(
        "/_dash-update-component",
        json={
            "output": output,
            "outputs": outputs,
            "inputs": inputs,
            "state": state or [],
            "changedPropIds": [changed or f"{inputs[0]['id']}.value"],
        },
    )


@pytest.mark.parametrize("tab", ["operations", "quality", "statistics"])
def test_tabs_render_through_dash(tab):
    response = callback_request(
        "page.children",
        {"id": "page", "property": "children"},
        [
            {"id": "tabs", "property": "value", "value": tab},
            {"id": "auth-revision", "property": "data", "value": 0},
        ],
    )
    assert response.status_code == 200
    assert response.get_json()["response"]["page"]["children"]["type"] == "Div"


@pytest.mark.parametrize("product", [product[1] for product in PRODUCTS])
def test_statistics_filters_render_for_each_product(product):
    released = result_view(dashboard.repo)
    released = released.loc[
        released.is_current.astype(bool)
        & released.review_status.astype(str).str.startswith("freigegeben")
        & (released["product"] == product)
    ]
    methods = sorted(released.method.unique())
    assert methods
    for method in methods:
        sample_type_rows = released.loc[released.method == method]
        sample_type = sorted(sample_type_rows.sample_type.unique())[0]
        parameter_callback = next(
            key for key in app.callback_map if key.startswith("..stats-parameter.options...")
        )
        outputs = [
            {"id": item.component_id, "property": item.component_property}
            for item in app.callback_map[parameter_callback]["output"]
        ]
        response = callback_request(
            parameter_callback,
            outputs,
            [
                {"id": "stats-product", "property": "value", "value": product},
                {"id": "stats-method", "property": "value", "value": method},
                {"id": "stats-sample-type", "property": "value", "value": sample_type},
            ],
        )
        assert response.status_code == 200
        options = response.get_json()["response"]["stats-parameter"]["options"]
        selected = response.get_json()["response"]["stats-parameter"]["value"]
        assert selected in options
        response = callback_request(
            "stats-content.children",
            {"id": "stats-content", "property": "children"},
            [
                {"id": "stats-product", "property": "value", "value": product},
                {"id": "stats-method", "property": "value", "value": method},
                {"id": "stats-sample-type", "property": "value", "value": sample_type},
                {"id": "stats-parameter", "property": "value", "value": selected},
                {"id": "stats-range", "property": "value", "value": "all"},
                {"id": "stats-start", "property": "date", "value": None},
                {"id": "stats-end", "property": "date", "value": None},
                {"id": "stats-quality", "property": "value", "value": "Alle"},
            ],
        )
        assert response.status_code == 200
        children = response.get_json()["response"]["stats-content"]["children"]["props"]["children"]
        assert any(child.get("type") == "Graph" for child in children)


def test_demo_queue_has_current_deadlines_and_past_results():
    now = datetime(2026, 10, 7, 13, 30)
    data = generate_demo_data(now=now)
    tasks = data["tasks"]
    pending = tasks.loc[tasks["status"] != TaskStatus.RELEASED.value]
    assert not pending.empty
    assert (pending["deadline"] > now).any()
    assert (pending["deadline"] < now).any()
    assert (pending["received_at"] >= now - timedelta(days=2)).all()
    assert (data["samples"]["received_at"] <= now).all()
    assert (data["results"]["measured_at"] <= now).all()
    assert (data["results"]["measured_at"] < now - timedelta(days=30)).any()


def test_open_priority_chart_includes_each_priority():
    dashboard = operations_layout(Repository(":memory:"))
    chart = next(component for component in dashboard.children if isinstance(component, dcc.Graph))
    chart_priorities = {priority for trace in chart.figure.data for priority in trace.x}
    assert chart_priorities == {"Normal", "Hoch", "Kritisch"}


def refresh_queue_request(active_filter, revision=0, search=""):
    output = next(key for key in app.callback_map if key.startswith("..queue.data..."))
    outputs = [
        {"id": item.component_id, "property": item.component_property}
        for item in app.callback_map[output]["output"]
    ]
    response = callback_request(
        output,
        outputs,
        [
            {"id": "queue-filter", "property": "data", "value": active_filter},
            {"id": "queue-revision", "property": "data", "value": revision},
            {"id": "queue-search", "property": "value", "value": search},
            {"id": "queue-clock", "property": "n_intervals", "value": 0},
        ],
    )
    assert response.status_code == 200
    return response.get_json()["response"]


@pytest.mark.parametrize(
    "active_filter",
    ["all", "open", "overdue", "progress", "critical", "review", "completed", "cancelled", "history"],
)
def test_queue_filter_matches_visible_tasks_and_clears_selection(active_filter):
    response = refresh_queue_request(active_filter)
    tasks = task_view(dashboard.repo)
    today = datetime.now().date()
    active_statuses = {
        TaskStatus.OPEN.value, TaskStatus.CLAIMED.value, TaskStatus.IN_PROGRESS.value,
        TaskStatus.RESULT_RECORDED.value, TaskStatus.REVIEW_REQUIRED.value,
    }
    predicates = {
        "all": lambda row: row.status in active_statuses,
        "open": lambda row: row.status in active_statuses,
        "overdue": lambda row: row.remaining_hours < 0 and row.status in active_statuses,
        "progress": lambda row: row.status == TaskStatus.IN_PROGRESS.value,
        "critical": lambda row: row.priority == "Kritisch" and row.status in active_statuses,
        "review": lambda row: row.status == TaskStatus.REVIEW_REQUIRED.value,
        "completed": lambda row: row.status == TaskStatus.RELEASED.value and row.completed_at.date() == today,
        "cancelled": lambda row: row.status == TaskStatus.CANCELLED.value,
        "history": lambda row: True,
    }
    expected = {row.task_id for row in tasks.itertuples() if predicates[active_filter](row)}
    actual = {row["task_id"] for row in response["queue"]["data"]}
    assert actual == expected
    assert response["queue"]["selected_row_ids"] == []
    assert response["queue"]["page_current"] == 0
    if active_filter in {"open", "progress", "critical", "overdue"}:
        assert int(response[f"kpi-{active_filter}-value"]["children"]) == len(expected)
        assert response[f"kpi-{active_filter}"]["aria-pressed"] == "true"


def test_sample_search_includes_closed_orders():
    tasks = task_view(dashboard.repo)
    completed = tasks.loc[tasks.status == TaskStatus.RELEASED.value].iloc[0]
    response = refresh_queue_request("all", search=completed.sample_id)
    assert completed.task_id in {row["task_id"] for row in response["queue"]["data"]}


def test_release_uses_stable_selected_row_id_and_refreshes_queue(isolated_logged_in_user):
    local_repo = isolated_logged_in_user
    task = local_repo.table("tasks").loc[
        local_repo.table("tasks").status == TaskStatus.REVIEW_REQUIRED.value
    ].iloc[0]
    output = next(key for key in app.callback_map if key.startswith("..workflow-message.children..."))
    outputs = [
        {"id": item.component_id, "property": item.component_property}
        for item in app.callback_map[output]["output"]
    ]
    response = callback_request(
        output,
        outputs,
        [
            {"id": "claim", "property": "n_clicks", "value": 0},
            {"id": "start", "property": "n_clicks", "value": 0},
            {"id": "review", "property": "n_clicks", "value": 0},
            {"id": "release", "property": "n_clicks", "value": 1},
            {"id": "record", "property": "n_clicks", "value": 0},
            {"id": "task-controls-save", "property": "n_clicks", "value": 0},
            {"id": "task-reassign", "property": "n_clicks", "value": 0},
            {"id": "task-reopen", "property": "n_clicks", "value": 0},
        ],
        [
            {"id": "queue", "property": "selected_row_ids", "value": [task.task_id]},
            {"id": "result-value", "property": "value", "value": None},
            {"id": "result-comment", "property": "value", "value": ""},
            {"id": "task-priority", "property": "value", "value": None},
            {"id": "task-deadline", "property": "value", "value": None},
            {"id": "task-reassign-employee", "property": "value", "value": None},
            {"id": "task-change-reason", "property": "value", "value": None},
            {"id": "queue-revision", "property": "data", "value": 0},
        ],
        "release.n_clicks",
    )
    assert response.status_code == 200
    assert response.get_json()["response"]["workflow-message"]["children"].startswith(task.task_id)
    assert local_repo.table("tasks").loc[
        local_repo.table("tasks").task_id == task.task_id, "status"
    ].iloc[0] == TaskStatus.RELEASED.value
    assert local_repo.events(task.task_id)


def test_lab_lead_can_apply_reasoned_task_priority_change(isolated_logged_in_user):
    local_repo = isolated_logged_in_user
    task = local_repo.table("tasks").loc[
        local_repo.table("tasks").status == TaskStatus.OPEN.value
    ].iloc[0]
    output = next(
        key for key in app.callback_map
        if key.startswith("..workflow-message.children...")
    )
    outputs = [
        {"id": item.component_id, "property": item.component_property}
        for item in app.callback_map[output]["output"]
    ]
    response = callback_request(
        output,
        outputs,
        [
            {"id": "claim", "property": "n_clicks", "value": 0},
            {"id": "start", "property": "n_clicks", "value": 0},
            {"id": "review", "property": "n_clicks", "value": 0},
            {"id": "release", "property": "n_clicks", "value": 0},
            {"id": "record", "property": "n_clicks", "value": 0},
            {"id": "task-controls-save", "property": "n_clicks", "value": 1},
            {"id": "task-reassign", "property": "n_clicks", "value": 0},
            {"id": "task-reopen", "property": "n_clicks", "value": 0},
        ],
        [
            {"id": "queue", "property": "selected_row_ids", "value": [task.task_id]},
            {"id": "result-value", "property": "value", "value": None},
            {"id": "result-comment", "property": "value", "value": ""},
            {"id": "task-priority", "property": "value", "value": "Kritisch"},
            {"id": "task-deadline", "property": "value", "value": None},
            {"id": "task-reassign-employee", "property": "value", "value": None},
            {"id": "task-change-reason", "property": "value", "value": "Produktionsengpass"},
            {"id": "queue-revision", "property": "data", "value": 0},
        ],
        "task-controls-save.n_clicks",
    )
    assert response.status_code == 200
    assert response.get_json()["response"]["workflow-message"]["children"].startswith(
        f"{task.task_id}: Aktion erfolgreich"
    )
    adjusted = local_repo.table("tasks").loc[
        local_repo.table("tasks").task_id == task.task_id
    ].iloc[0]
    assert adjusted.priority == "Kritisch"


def test_admin_account_management_callback_deactivates_selected_account(isolated_logged_in_user):
    local_repo = isolated_logged_in_user
    with client.session_transaction() as user_session:
        user_session["username"] = "admin"
    output = next(
        key for key in app.callback_map
        if key.startswith("..local-user-message.children...")
    )
    outputs = [
        {"id": item.component_id, "property": item.component_property}
        for item in app.callback_map[output]["output"]
    ]
    response = callback_request(
        output,
        outputs,
        [
            {"id": "local-user-create", "property": "n_clicks", "value": 0},
            {"id": "local-user-reset", "property": "n_clicks", "value": 0},
            {"id": "local-user-deactivate", "property": "n_clicks", "value": 1},
            {"id": "local-user-activate", "property": "n_clicks", "value": 0},
        ],
        [
            {"id": "local-user-name", "property": "value", "value": None},
            {"id": "local-user-password", "property": "value", "value": None},
            {"id": "local-user-role", "property": "value", "value": "Laborant"},
            {"id": "local-user-employee", "property": "value", "value": "E-01"},
            {"id": "local-user-list", "property": "selected_row_ids", "value": ["lab"]},
            {"id": "local-user-reset-password", "property": "value", "value": None},
        ],
        "local-user-deactivate.n_clicks",
    )
    assert response.status_code == 200
    result = response.get_json()["response"]["local-user-message"]["children"]
    assert result == "Konto 'lab' deaktiviert."
    assert local_repo.local_user("lab")["active"] == 0


def test_admin_page_renders_local_account_management_controls():
    with client.session_transaction() as user_session:
        user_session["username"] = "admin"
    response = callback_request(
        "page.children",
        {"id": "page", "property": "children"},
        [
            {"id": "tabs", "property": "value", "value": "operations"},
            {"id": "auth-revision", "property": "data", "value": 1},
        ],
    )
    assert response.status_code == 200
    content = str(response.get_json()["response"]["page"]["children"])
    assert "Kennwort zurücksetzen" in content
    assert "Konto deaktivieren" in content


def test_sample_detail_callback_shows_order_and_result_history(isolated_logged_in_user):
    sample_id = isolated_logged_in_user.table("samples").iloc[0].sample_id
    output = next(
        key for key in app.callback_map
        if key.startswith("..sample-detail-content.children...")
    )
    response = callback_request(
        output,
        [
            {"id": "sample-detail-content", "property": "children"},
            {"id": "sample-edit-name", "property": "value"},
            {"id": "sample-edit-batch", "property": "value"},
            {"id": "sample-edit-notes", "property": "value"},
        ],
        [
            {"id": "sample-detail-id", "property": "value", "value": sample_id},
            {"id": "sample-detail-revision", "property": "data", "value": 0},
        ],
        changed="sample-detail-id.value",
    )
    assert response.status_code == 200
    children = response.get_json()["response"]["sample-detail-content"]["children"]
    assert children["type"] == "Div"
    assert "Messungen und Ergebnisversionen" in str(children)


def test_sample_update_callback_saves_only_for_lab_lead(isolated_logged_in_user):
    local_repo = isolated_logged_in_user
    sample_id = local_repo.table("samples").iloc[0].sample_id
    output = next(
        key for key in app.callback_map
        if key.startswith("..sample-edit-message.children...")
    )
    response = callback_request(
        output,
        [
            {"id": "sample-edit-message", "property": "children"},
            {"id": "sample-detail-revision", "property": "data"},
        ],
        [{"id": "sample-edit-save", "property": "n_clicks", "value": 1}],
        [
            {"id": "sample-detail-id", "property": "value", "value": sample_id},
            {"id": "sample-edit-name", "property": "value", "value": "Edited sample"},
            {"id": "sample-edit-batch", "property": "value", "value": "B-EDITED"},
            {"id": "sample-edit-notes", "property": "value", "value": "Updated in UI"},
            {"id": "sample-edit-reason", "property": "value", "value": "Incoming record correction"},
            {"id": "sample-detail-revision", "property": "data", "value": 0},
        ],
        "sample-edit-save.n_clicks",
    )
    assert response.status_code == 200
    result = response.get_json()["response"]["sample-edit-message"]["children"]
    assert result.startswith("Probendaten gespeichert")
    saved = local_repo.table("samples").loc[
        local_repo.table("samples").sample_id == sample_id
    ].iloc[0]
    assert saved.sample_name == "Edited sample"
    with client.session_transaction() as user_session:
        user_session["username"] = "lab"
    denied = callback_request(
        output,
        [
            {"id": "sample-edit-message", "property": "children"},
            {"id": "sample-detail-revision", "property": "data"},
        ],
        [{"id": "sample-edit-save", "property": "n_clicks", "value": 2}],
        [
            {"id": "sample-detail-id", "property": "value", "value": sample_id},
            {"id": "sample-edit-name", "property": "value", "value": "Must not persist"},
            {"id": "sample-edit-batch", "property": "value", "value": "B"},
            {"id": "sample-edit-notes", "property": "value", "value": "No"},
            {"id": "sample-edit-reason", "property": "value", "value": "Reason"},
            {"id": "sample-detail-revision", "property": "data", "value": 1},
        ],
        "sample-edit-save.n_clicks",
    )
    assert denied.status_code == 200
    assert "Nur die Laborleitung" in denied.get_json()["response"]["sample-edit-message"]["children"]
    assert local_repo.table("samples").loc[
        local_repo.table("samples").sample_id == sample_id, "sample_name"
    ].iloc[0] == "Edited sample"


def test_oos_case_management_callback_opens_and_closes_case(isolated_logged_in_user):
    local_repo = isolated_logged_in_user
    result = local_repo.table("results").loc[
        local_repo.table("results").quality_status == "OOS"
    ].iloc[0]
    output = next(
        key for key in app.callback_map
        if key.startswith("..oos-case-message.children...")
    )
    outputs = [
        {"id": item.component_id, "property": item.component_property}
        for item in app.callback_map[output]["output"]
    ]
    open_inputs = [
        {"id": "oos-case-open", "property": "n_clicks", "value": 1},
        {"id": "oos-case-close", "property": "n_clicks", "value": 0},
    ]
    state = [
        {"id": "oos-result-id", "property": "value", "value": result.result_id},
        {"id": "oos-initial-description", "property": "value", "value": "Demo investigation opened."},
        {"id": "oos-case-list", "property": "selected_row_ids", "value": []},
        {"id": "oos-root-cause", "property": "value", "value": None},
        {"id": "oos-corrective-action", "property": "value", "value": None},
        {"id": "oos-closure-rationale", "property": "value", "value": None},
    ]
    opened = callback_request(
        output, outputs, open_inputs, state, "oos-case-open.n_clicks"
    )
    assert opened.status_code == 200
    opened_payload = opened.get_json()["response"]
    case_id = opened_payload["oos-case-list"]["data"][0]["case_id"]
    assert opened_payload["oos-case-message"]["children"] == f"OOS-Fall {case_id} eröffnet."

    close_inputs = [
        {"id": "oos-case-open", "property": "n_clicks", "value": 1},
        {"id": "oos-case-close", "property": "n_clicks", "value": 1},
    ]
    close_state = [
        {"id": "oos-result-id", "property": "value", "value": result.result_id},
        {"id": "oos-initial-description", "property": "value", "value": "Demo investigation opened."},
        {"id": "oos-case-list", "property": "selected_row_ids", "value": [case_id]},
        {"id": "oos-root-cause", "property": "value", "value": "Demo root cause."},
        {"id": "oos-corrective-action", "property": "value", "value": "Containment recorded."},
        {"id": "oos-closure-rationale", "property": "value", "value": "Demo investigation completed."},
    ]
    closed = callback_request(
        output, outputs, close_inputs, close_state, "oos-case-close.n_clicks"
    )
    assert closed.status_code == 200
    closed_payload = closed.get_json()["response"]
    assert "der Ergebnisstatus bleibt OOS" in closed_payload["oos-case-message"]["children"]
    assert closed_payload["oos-case-list"]["data"][0]["status"] == "Abgeschlossen"
    assert local_repo.table("results").loc[
        local_repo.table("results").result_id == result.result_id, "quality_status"
    ].iloc[0] == "OOS"
