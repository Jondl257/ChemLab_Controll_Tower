from dash import dcc, html, dash_table
import plotly.express as px
from components.ui import kpi
from config import COLORS
from services.analytics_service import result_view

def layout(repo):
    r=result_view(repo); count=r.quality_status.value_counts(); total=len(r); oos=int(count.get("OOS",0));
    fig=px.bar(r.groupby(["product","quality_status"]).size().reset_index(name="Anzahl"),x="product",y="Anzahl",color="quality_status",barmode="stack",color_discrete_map={"PASS":COLORS["pass"],"GRENZNAH":COLORS["near_limit"],"OOS":COLORS["oos"]},title="Qualitätsstatus nach Produkt")
    cols=["product","method","parameter","value","unit","lsl","usl","quality_status","measured_at"]
    return html.Div([html.Div([kpi("ERGEBNISSE",str(total)),kpi("PASS",str(int(count.get("PASS",0)))),kpi("OOS",str(oos)),kpi("OOS-RATE",f"{(100*oos/total if total else 0):.1f}%")],className="kpi-grid"),dcc.Graph(figure=fig),html.H3("Quality Drill-down"),dash_table.DataTable(r[cols].round(3).to_dict("records"),[{"name":c,"id":c} for c in cols],page_size=12,sort_action="native",filter_action="native",style_table={"overflowX":"auto"},style_cell={"fontFamily":"Arial","fontSize":12,"padding":"8px"})])
