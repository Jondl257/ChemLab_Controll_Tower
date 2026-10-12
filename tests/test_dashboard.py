from datetime import datetime, timedelta

import pytest
from dash import dcc

from app import app, params, repo
from data.repository import Repository
from services.analytics_service import task_view
from data.generator import generate_demo_data
from domain.enums import TaskStatus
from pages.operations import layout as operations_layout


def callback_request(output, outputs, inputs, state=None, changed=None):
    return app.server.test_client().post(
        "/_dash-update-component",
        json={"output": output, "outputs": outputs, "inputs": inputs,
              "state": state or [], "changedPropIds": [changed or f"{inputs[0]['id']}.value"]},
    )


@pytest.mark.parametrize("tab", ["operations", "quality", "statistics"])
def test_tabs_render_through_dash(tab):
    response = callback_request(
        "page.children", {"id": "page", "property": "children"},
        [{"id": "tabs", "property": "value", "value": tab}],
    )
    assert response.status_code == 200
    assert response.get_json()["response"]["page"]["children"]["type"] == "Div"


@pytest.mark.parametrize("product", sorted(repo.table("products")["product"]))
def test_statistics_filters_render_for_each_product(product):
    response = callback_request(
        "..stats-parameter.options...stats-parameter.value..",
        [{"id": "stats-parameter", "property": "options"},
         {"id": "stats-parameter", "property": "value"}],
        [{"id": "stats-product", "property": "value", "value": product}],
    )
    assert response.status_code == 200
    options, selected = params(product)
    assert response.get_json()["response"]["stats-parameter"]["value"] == selected
    for parameter in options:
        response = callback_request(
            "stats-content.children", {"id": "stats-content", "property": "children"},
            [{"id": "stats-product", "property": "value", "value": product},
             {"id": "stats-parameter", "property": "value", "value": parameter}],
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
    dashboard = operations_layout(Repository())
    chart = next(component for component in dashboard.children if isinstance(component, dcc.Graph))
    chart_priorities = {priority for trace in chart.figure.data for priority in trace.x}
    assert chart_priorities == {"Normal", "Hoch", "Kritisch"}


def refresh_queue_request(active_filter, revision=0):
    output=next(key for key in app.callback_map if key.startswith("..queue.data..."))
    outputs=[{"id":item.component_id,"property":item.component_property} for item in app.callback_map[output]["output"]]
    response=callback_request(output,outputs,[
        {"id":"queue-filter","property":"data","value":active_filter},
        {"id":"queue-revision","property":"data","value":revision},
    ])
    assert response.status_code==200
    return response.get_json()["response"]


@pytest.mark.parametrize("active_filter", ["all","open","overdue","progress","completed"])
def test_card_filter_matches_visible_tasks_and_clears_selection(active_filter):
    response=refresh_queue_request(active_filter)
    tasks=task_view(repo)
    today=datetime.now().date()
    predicates={
        "all":lambda row: True,
        "open":lambda row: row.status in (TaskStatus.OPEN.value,TaskStatus.CLAIMED.value,TaskStatus.IN_PROGRESS.value),
        "overdue":lambda row: row.remaining_hours<0 and row.status not in (TaskStatus.RELEASED.value,TaskStatus.CANCELLED.value),
        "progress":lambda row: row.status==TaskStatus.IN_PROGRESS.value,
        "completed":lambda row: row.status==TaskStatus.RELEASED.value and row.completed_at.date()==today,
    }
    expected={row.task_id for row in tasks.itertuples() if predicates[active_filter](row)}
    assert {row["task_id"] for row in response["queue"]["data"]}==expected
    assert response["queue"]["selected_rows"]==[]
    assert response["queue"]["page_current"]==0
    if active_filter!="all":
        assert int(response[f"kpi-{active_filter}-value"]["children"])==len(expected)
        assert response[f"kpi-{active_filter}"]["aria-pressed"]=="true"


def test_card_click_toggles_and_show_all_resets_filter():
    outputs={"id":"queue-filter","property":"data"}
    for current,clicked,expected in [("all","kpi-open","open"),("open","kpi-open","all"),("open","kpi-overdue","overdue"),("overdue","queue-show-all","all")]:
        inputs=[{"id":component,"property":"n_clicks","value":1 if component==clicked else 0} for component in ("kpi-open","kpi-overdue","kpi-progress","kpi-completed","queue-show-all")]
        response=callback_request("queue-filter.data",outputs,inputs,[{"id":"queue-filter","property":"data","value":current}],f"{clicked}.n_clicks")
        assert response.status_code==200
        assert response.get_json()["response"]["queue-filter"]["data"]==expected


def test_release_updates_today_count_and_preserves_queue_filter(monkeypatch):
    import app as dashboard
    from services.workflow_service import WorkflowService
    local_repo=Repository()
    monkeypatch.setattr(dashboard,"repo",local_repo)
    monkeypatch.setattr(dashboard,"workflow",WorkflowService(local_repo))
    tasks=local_repo.table("tasks")
    task=tasks.loc[tasks.status==TaskStatus.REVIEW_REQUIRED.value].iloc[0]
    before=refresh_queue_request("completed")
    action_ids=("claim","start","review","release","record")
    state=[{"id":component,"property":prop,"value":value} for component,prop,value in (
        ("queue","selected_rows",[0]),("queue","derived_viewport_data",[{"task_id":task.task_id}]),
        ("employee","value","E-01"),("result-value","value",None),("result-comment","value",""),("queue-revision","data",0),
    )]
    response=callback_request("..workflow-message.children...queue-revision.data..",[{"id":"workflow-message","property":"children"},{"id":"queue-revision","property":"data"}],
        [{"id":key,"property":"n_clicks","value":int(key=="release")} for key in action_ids],state,"release.n_clicks")
    assert response.status_code==200
    assert response.get_json()["response"]["queue-revision"]["data"]==1
    after=refresh_queue_request("completed",1)
    assert int(after["kpi-completed-value"]["children"])==int(before["kpi-completed-value"]["children"])+1
    released=next(row for row in after["queue"]["data"] if row["task_id"]==task.task_id)
    assert released["deadline"]=="-"
    assert after["kpi-completed"]["aria-pressed"]=="true"
    overdue=refresh_queue_request("overdue",1)
    assert task.task_id not in {row["task_id"] for row in overdue["queue"]["data"]}
