from dash import dcc, html, dash_table
import plotly.express as px
from components.ui import kpi
from config import PRIMARY
from services.analytics_service import task_view, queue_records, queue_masks

QUEUE_COLUMNS=["priority","task_id","sample_id","product","product_class","sample_type","method","deadline","remaining_hours","employee","instrument_id","status"]
FILTER_LABELS={"all":"Alle Analysen","open":"Offene Analysen","overdue":"Überfällige Analysen","progress":"In Bearbeitung","completed":"Heute abgeschlossen"}

def queue_content(repo, active_filter="all"):
    tasks=task_view(repo)
    masks=queue_masks(tasks)
    filtered=tasks.loc[masks[active_filter]] if active_filter in masks else tasks
    return queue_records(filtered[QUEUE_COLUMNS]), {key:int(mask.sum()) for key,mask in masks.items()}

def layout(repo):
    t=task_view(repo); masks=queue_masks(t); open_=masks["open"]
    cols=QUEUE_COLUMNS
    chart=px.bar(t[open_].groupby("priority").size().reset_index(name="Anzahl"),x="priority",y="Anzahl",color="priority",color_discrete_map={"Normal":"#667085","Hoch":"#B06D00","Kritisch":"#B42318"},title="Offene Analysen nach Priorität")
    employees=repo.table("employees").query("role == 'Laborant'")
    options=[{"label":row.employee,"value":row.employee_id} for row in employees.itertuples()]
    controls=html.Div([html.H3("Workflow-Aktion"),html.Div([dcc.Dropdown(options,options[0]["value"],id="employee",clearable=False),html.Button("Übernehmen",id="claim",className="primary"),html.Button("Starten",id="start",className="primary"),html.Button("Prüfung anfordern",id="review",className="secondary"),html.Button("Freigeben",id="release",className="secondary")],className="action-row"),html.Div([dcc.Input(id="result-value",type="number",placeholder="Messwert"),dcc.Input(id="result-comment",type="text",placeholder="Kommentar"),html.Button("Ergebnis erfassen",id="record",className="primary")],className="action-row"),html.Div(id="workflow-message",className="message")])
    table=dash_table.DataTable(queue_records(t[cols]),[{"name":c,"id":c} for c in cols],id="queue",page_size=12,sort_action="native",filter_action="native",row_selectable="single",style_table={"overflowX":"auto"},style_cell={"fontFamily":"Arial","fontSize":12,"padding":"8px","textAlign":"left"})
    cards=[kpi("OFFENE ANALYSEN",str(masks["open"].sum()),button_id="kpi-open"),kpi("ÜBERFÄLLIG",str(masks["overdue"].sum()),"synthetische Demo-SLAs",button_id="kpi-overdue"),kpi("IN BEARBEITUNG",str(masks["progress"].sum()),button_id="kpi-progress"),kpi("HEUTE ABGESCHLOSSEN",str(masks["completed"].sum()),button_id="kpi-completed")]
    return html.Div([dcc.Store(id="queue-filter",data="all"),dcc.Store(id="queue-revision",data=0),html.Div(cards,className="kpi-grid"),dcc.Graph(figure=chart),html.H3("Analyse-Queue"),html.Div([html.Span("Alle Analysen",id="queue-filter-label"),html.Button("Alle anzeigen",id="queue-show-all",n_clicks=0,type="button")],className="queue-filter-bar"),html.P("Übersichtskarte anklicken, um die Liste zu filtern. Erneuter Klick hebt den Filter auf. Zeile markieren, dann eine Workflow-Aktion ausführen."),table,controls])
