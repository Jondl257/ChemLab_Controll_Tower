from dash import Dash, Input, Output, State, ctx, dcc, html, no_update
from data.repository import Repository
from pages import operations, quality, statistics
from config import APP_TITLE
from services.workflow_service import WorkflowService
from domain.enums import TaskStatus

repo=Repository(); app=Dash(__name__,title=APP_TITLE,suppress_callback_exceptions=True)
workflow=WorkflowService(repo)
app.layout=html.Div([html.Header([html.Div([html.H1(APP_TITLE),html.P("Synthetic demo data · not a validated LIMS or GMP system")]),html.Div("Rolle: Laborleiter (simuliert)")]),dcc.Tabs(id="tabs",value="operations",children=[dcc.Tab(label="Laboratory Operations",value="operations"),dcc.Tab(label="Quality Control",value="quality"),dcc.Tab(label="Statistics",value="statistics")]),html.Main(id="page",className="content")])
@app.callback(Output("page","children"),Input("tabs","value"))
def page(tab): return {"operations":operations.layout,"quality":quality.layout,"statistics":statistics.layout}[tab](repo)
@app.callback(Output("stats-parameter","options"),Output("stats-parameter","value"),Input("stats-product","value"))
def params(product):
    r=statistics.result_view(repo); values=sorted(r.loc[r["product"]==product,"parameter"].unique()); return values,values[0] if values else None
@app.callback(Output("stats-content","children"),Input("stats-product","value"),Input("stats-parameter","value"))
def stats(product,parameter): return statistics.content(repo,product,parameter)

QUEUE_FILTERS=("open","overdue","progress","completed")

@app.callback(Output("queue-filter","data"),*[Input(f"kpi-{key}","n_clicks") for key in QUEUE_FILTERS],Input("queue-show-all","n_clicks"),State("queue-filter","data"),prevent_initial_call=True)
def select_queue_filter(*args):
    if not ctx.triggered or not ctx.triggered[0]["value"]: return no_update
    clicked=ctx.triggered_id
    if clicked=="queue-show-all": return "all"
    chosen=clicked.removeprefix("kpi-")
    return "all" if args[-1]==chosen else chosen

@app.callback(Output("queue","data"),Output("queue","selected_rows"),Output("queue","page_current"),Output("queue-filter-label","children"),*[output for key in QUEUE_FILTERS for output in (Output(f"kpi-{key}-value","children"),Output(f"kpi-{key}","className"),Output(f"kpi-{key}","aria-pressed"))],Input("queue-filter","data"),Input("queue-revision","data"))
def refresh_queue(active_filter, revision):
    rows,counts=operations.queue_content(repo,active_filter)
    values=[rows,[],0,f"{operations.FILTER_LABELS.get(active_filter,'Alle Analysen')} ({len(rows)})"]
    for key in QUEUE_FILTERS:
        active=key==active_filter
        values.extend([str(counts[key]),"kpi kpi-button active" if active else "kpi kpi-button","true" if active else "false"])
    return values

@app.callback(Output("workflow-message","children"),Output("queue-revision","data"),Input("claim","n_clicks"),Input("start","n_clicks"),Input("review","n_clicks"),Input("release","n_clicks"),Input("record","n_clicks"),State("queue","selected_rows"),State("queue","derived_viewport_data"),State("employee","value"),State("result-value","value"),State("result-comment","value"),State("queue-revision","data"),prevent_initial_call=True)
def apply_action(*args):
    selected, rows, employee, value, comment, revision = args[-6:]
    if not selected or not rows: return "Bitte zuerst genau einen Analyseauftrag markieren.", no_update
    task_id=rows[selected[0]]["task_id"]
    try:
        action=ctx.triggered_id
        if action=="claim": workflow.transition(task_id,TaskStatus.CLAIMED.value,employee)
        elif action=="start": workflow.transition(task_id,TaskStatus.IN_PROGRESS.value)
        elif action=="review": workflow.transition(task_id,TaskStatus.REVIEW_REQUIRED.value)
        elif action=="release": workflow.transition(task_id,TaskStatus.RELEASED.value)
        elif action=="record":
            if value is None: raise ValueError("Für die Ergebniserfassung ist ein Messwert erforderlich.")
            workflow.record_result(task_id,value,comment or "")
        message=f"{task_id}: Aktion erfolgreich ausgeführt."
    except ValueError as exc: message=f"Keine Änderung: {exc}"
    return message, (revision or 0)+1
if __name__=="__main__": app.run(debug=True)
