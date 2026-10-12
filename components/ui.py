from dash import html
def kpi(label, value, detail="", button_id=None):
    value_props={"id": f"{button_id}-value"} if button_id else {}
    children=[html.Div(label,className="kpi-label"),html.Div(value,className="kpi-value",**value_props),html.Div(detail,className="kpi-detail")]
    if button_id:
        return html.Button(children,id=button_id,n_clicks=0,type="button",className="kpi kpi-button",**{"aria-pressed": "false"})
    return html.Div(children,className="kpi")
