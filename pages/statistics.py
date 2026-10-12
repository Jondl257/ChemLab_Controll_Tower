from dash import dcc, html
import plotly.graph_objects as go
from components.ui import kpi
from config import COLORS
from services.analytics_service import result_view, statistics

def layout(repo):
    r=result_view(repo)
    products=sorted(r["product"].unique())
    product=products[0] if products else None
    parameters=sorted(r.loc[r["product"]==product,"parameter"].unique())
    parameter=parameters[0] if parameters else None
    return html.Div([html.Div([html.Label("Produkt"),dcc.Dropdown(products,product,id="stats-product",clearable=False),html.Label("Parameter"),dcc.Dropdown(parameters,parameter,id="stats-parameter",clearable=False)],className="filters"),html.Div(content(repo,product,parameter),id="stats-content")])
def content(repo,product,parameter):
    r,s=statistics(repo,product,parameter)
    def f(x):
        return "N/A" if x is None else f"{x:.3f}"
    cards=html.Div([kpi("n",str(s["n"])),kpi("MITTELWERT",f(s["mean"])),kpi("STDABW.",f(s["std"])),kpi("Cp",f(s["cp"])),kpi("Cpk",f(s["cpk"]))],className="kpi-grid")
    if r.empty:return html.Div([cards,html.P("Keine Daten für diese Auswahl.")])
    r=r.sort_values("measured_at"); fig=go.Figure(); fig.add_scatter(x=r.measured_at,y=r.value,mode="lines+markers",name="Messwert",line={"color":"#004A96"})
    for key,label,color,dash in [("target","Sollwert","#667085","dot"),("lsl","LSL",COLORS["oos"],"dash"),("usl","USL",COLORS["oos"],"dash")]:fig.add_hline(y=float(r[key].iloc[0]),line_color=color,line_dash=dash,annotation_text=label)
    if s["ucl"] is not None:
        fig.add_hline(y=s["ucl"],line_color="#B06D00",line_dash="dot",annotation_text="UCL (3σ)");fig.add_hline(y=s["lcl"],line_color="#B06D00",line_dash="dot",annotation_text="LCL (3σ)")
    fig.update_layout(title="Zeitreihe mit Spezifikations- und Kontrollgrenzen",plot_bgcolor="white",paper_bgcolor="white",xaxis_title="Zeitpunkt",yaxis_title=r.unit.iloc[0])
    return html.Div([cards,dcc.Graph(figure=fig),html.P("Kontrollgrenzen sind statistische Demo-Kontrollgrenzen und nicht mit Spezifikationsgrenzen gleichzusetzen.",className="note")])
