from __future__ import annotations

from typing import Mapping, Sequence
import pandas as pd
import plotly.graph_objects as go

PASTEL={"hydro":"#9DCFEB","thermal":"#F4B4B4","wind":"#B1DDBE","solar":"#F8DD94"}


def ramp_figures(annual:pd.DataFrame, distribution:pd.DataFrame, heatmap:pd.DataFrame, labels:Mapping[str,str], unit:str, metrics:Sequence[str], heat_unit:str|None=None):
    f1=go.Figure()
    colors={"max_up":"#7FB3D5","max_down":"#E6A0A0","p95_abs":"#8FC7A0","p99_abs":"#D8B75E"}
    for metric in metrics:
        if metric in annual:
            f1.add_trace(go.Scatter(x=annual["year"],y=annual[metric],mode="lines+markers",name=labels.get(metric,metric),line={"color":colors.get(metric)}))
    f1.update_layout(title=labels["severity_title"],height=300,margin=dict(l=55,r=20,t=50,b=40),hovermode="x unified",xaxis=dict(dtick=1,title=labels["year"]),yaxis_title=unit,plot_bgcolor="white")

    f2=go.Figure()
    if not distribution.empty:
        f2.add_trace(go.Scatter(x=distribution["year"],y=distribution["p95"],line=dict(width=0),showlegend=False,hoverinfo="skip"))
        f2.add_trace(go.Scatter(x=distribution["year"],y=distribution["p05"],fill="tonexty",fillcolor="rgba(127,179,213,.25)",line=dict(width=0),name="P05–P95"))
        f2.add_trace(go.Scatter(x=distribution["year"],y=distribution["p75"],line=dict(width=0),showlegend=False,hoverinfo="skip"))
        f2.add_trace(go.Scatter(x=distribution["year"],y=distribution["p25"],fill="tonexty",fillcolor="rgba(177,221,190,.55)",line=dict(width=0),name="P25–P75"))
        f2.add_trace(go.Scatter(x=distribution["year"],y=distribution["p50"],mode="lines+markers",name=labels["median"],line=dict(color="#526D82")))
    f2.update_layout(title=labels["distribution_title"],height=300,margin=dict(l=55,r=20,t=50,b=40),hovermode="x unified",xaxis=dict(dtick=1,title=labels["year"]),yaxis_title=unit,plot_bgcolor="white")

    f3=go.Figure(go.Heatmap(z=heatmap.values,x=[f"{int(h):02d}h" for h in heatmap.columns],y=heatmap.index.astype(str),colorscale=[[0,"#eef6f5"],[.5,"#9DCFEB"],[1,"#0b7a80"]],colorbar=dict(title=heat_unit or unit))) if not heatmap.empty else go.Figure()
    f3.update_layout(title=labels["heat_title"],height=390,margin=dict(l=55,r=45,t=50,b=40),xaxis_title=labels["hour"],yaxis_title=labels["year"],plot_bgcolor="white")
    return f1,f2,f3


def event_figures(ranking:pd.DataFrame, window:pd.DataFrame, source:str, center:pd.Timestamp, labels:Mapping[str,str]):
    f1=go.Figure()
    if not ranking.empty:
        display=ranking.sort_values("rank",ascending=False)
        f1.add_trace(go.Bar(x=display["value"],y=display["context"],orientation="h",marker_color="#9DCFEB",text=display["value"].round(2),textposition="outside"))
    f1.update_layout(title=labels["ranking"],height=330,margin=dict(l=150,r=30,t=50,b=35),plot_bgcolor="white")
    f2=go.Figure(); f3=go.Figure()
    if source=="BALANCO" and not window.empty:
        for col,name,color in [("val_carga",labels["load"],"#526D82"),("net_load",labels["net_load"],"#C9936B"),("val_gerhidraulica",labels["hydro"],"#78B6D8"),("val_gertermica",labels["thermal"],"#D99090"),("val_gereolica",labels["wind"],"#85B998"),("val_gersolar",labels["solar"],"#D8B75E"),("val_intercambio",labels["interchange"],"#9B8FC4")]:
            if col in window: f2.add_trace(go.Scatter(x=window["din_instante"],y=window[col],name=name,mode="lines",line=dict(color=color)))
        f2.add_vline(x=center,line_dash="dash",line_color="#c0392b",line_width=2)
        shares=[]
        denom=window["val_carga"].replace(0,pd.NA)
        for col,name,color in [("val_gerhidraulica",labels["hydro"],"#9DCFEB"),("val_gertermica",labels["thermal"],"#F4B4B4"),("val_gereolica",labels["wind"],"#B1DDBE"),("val_gersolar",labels["solar"],"#F8DD94")]:
            if col in window:
                f3.add_trace(go.Scatter(x=window["din_instante"],y=window[col].div(denom).mul(100),stackgroup="one",name=name,line=dict(width=.7,color=color)))
        f3.add_vline(x=center,line_dash="dash",line_color="#c0392b",line_width=2)
    else:
        date_col="ear_data" if source=="EAR" else "ena_data"
        candidates=[c for c in window.columns if c.endswith("percentual") or "percentualmlt" in c]
        if candidates:
            f2.add_trace(go.Scatter(x=window[date_col],y=window[candidates[0]],mode="lines+markers",name=source,line=dict(color="#0b7a80")))
            f2.add_vline(x=center,line_dash="dash",line_color="#c0392b",line_width=2)
    for fig,title in ((f2,labels["context"]),(f3,labels["profile"])):
        fig.update_layout(title=title,height=310,margin=dict(l=55,r=20,t=50,b=40),hovermode="x unified",plot_bgcolor="white")
    return f1,f2,f3


def matrix_figures(annual:pd.DataFrame, labels:Mapping[str,str], sources:Sequence[str], mode:str="growth", show_load:bool=True, show_interchange:bool=False, unit_label:str="MWmed"):
    source_cols={"hydro":"val_gerhidraulica","thermal":"val_gertermica","wind":"val_gereolica","solar":"val_gersolar"}
    f1=go.Figure()
    for source in sources:
        f1.add_trace(go.Scatter(x=annual["year"],y=annual[source_cols[source]],stackgroup="generation",name=labels[source],line=dict(color=PASTEL[source],width=.8),fillcolor=PASTEL[source]))
    if show_load: f1.add_trace(go.Scatter(x=annual["year"],y=annual["val_carga"],name=labels["load"],line=dict(color="#455A64",width=2.3)))
    f1.update_layout(title=labels["generation"],height=300,xaxis=dict(dtick=1),yaxis_title=unit_label,plot_bgcolor="white",margin=dict(l=55,r=20,t=50,b=40),hovermode="x unified")
    f2=go.Figure()
    for source in sources: f2.add_trace(go.Scatter(x=annual["year"],y=annual[f"share_{source}"],stackgroup="share",groupnorm="percent",name=labels[source],line=dict(color=PASTEL[source],width=.8),fillcolor=PASTEL[source]))
    f2.update_layout(title=labels["participation"],height=300,xaxis=dict(dtick=1),yaxis_title="%",plot_bgcolor="white",margin=dict(l=55,r=20,t=50,b=40),hovermode="x unified")
    f3=go.Figure(); prefix={"growth":"growth_","cumulative":"cumulative_","index":"index_","difference":"difference_"}.get(mode,"growth_")
    for source in sources:
        col=prefix+source
        if col in annual: f3.add_trace(go.Scatter(x=annual["year"],y=annual[col],mode="lines+markers",name=labels[source],line=dict(color=PASTEL[source])))
    f3.update_layout(title=labels["transformation"],height=300,xaxis=dict(dtick=1),yaxis_title="%" if mode!="difference" else unit_label,plot_bgcolor="white",margin=dict(l=55,r=20,t=50,b=40),hovermode="x unified")
    f4=go.Figure()
    f4.add_trace(go.Scatter(x=annual["year"],y=annual["val_carga"],name=labels["load"],line=dict(color="#455A64",width=2.3)))
    f4.add_trace(go.Scatter(x=annual["year"],y=annual["val_gerhidraulica"],name=labels["hydro"],line=dict(color=PASTEL["hydro"])))
    f4.add_trace(go.Scatter(x=annual["year"],y=annual["vre"],name=labels["vre"],line=dict(color="#85B998",width=2.1)))
    f4.add_trace(go.Scatter(x=annual["year"],y=annual["vre_share_load"],name=labels["vre_share"],yaxis="y2",line=dict(color="#D8B75E",dash="dash")))
    if show_interchange and "val_intercambio" in annual:
        f4.add_trace(go.Scatter(x=annual["year"],y=annual["val_intercambio"],name=labels.get("interchange","Intercâmbio"),line=dict(color="#9B8FC4",dash="dot")))
    f4.update_layout(title=labels["comparison"],height=310,xaxis=dict(dtick=1),yaxis_title=unit_label,yaxis2=dict(title="%",overlaying="y",side="right"),plot_bgcolor="white",margin=dict(l=55,r=55,t=50,b=40),hovermode="x unified")
    if "coverage" in annual:
        coverage=annual["coverage"]
        for fig in (f1,f2,f3,f4):
            fig.update_traces(customdata=coverage,hovertemplate="%{x}<br>%{y:.2f}<br>Cobertura: %{customdata:.1f}%<extra>%{fullData.name}</extra>")
    if "complete" in annual:
        incomplete=annual.loc[~annual["complete"].astype(bool),"year"]
        for year in incomplete:
            for fig in (f1,f2,f3,f4): fig.add_vrect(x0=float(year)-.45,x1=float(year)+.45,fillcolor="#c7c7c7",opacity=.14,line_width=0,layer="below")
    return f1,f2,f3,f4
