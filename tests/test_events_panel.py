import pandas as pd
from events_panel import event_candidates, rank_events, event_window, anomaly_score


def hourly():
    return pd.DataFrame({"din_instante":pd.date_range("2026-01-01",periods=6,freq="h"),"val_carga":[100,120,90,130,80,110],"val_gersolar":[0,5,10,5,0,0],"val_gereolica":[10]*6,"val_intercambio":[-5,10,-20,30,0,5]})

def test_rank_max_load_and_window():
    c=event_candidates("max_load",hourly=hourly())
    r=rank_events(c,2)
    assert r.iloc[0]["value"]==130
    w=event_window(r.iloc[0]["timestamp"],source="BALANCO",hourly=hourly(),hours=1)
    assert len(w)==3

def test_shares_import_export_and_anomalies():
    assert rank_events(event_candidates("max_solar_share",hourly=hourly()),1).iloc[0]["value"]>0
    assert rank_events(event_candidates("max_import",hourly=hourly()),1).iloc[0]["value"]==30
    assert rank_events(event_candidates("max_export",hourly=hourly()),1).iloc[0]["value"]==20
    assert anomaly_score(pd.Series([1,1,10]),"zscore").iloc[-1]>1

def test_ear_and_ena_events():
    ear=pd.DataFrame({"ear_data":pd.date_range("2026-01-01",periods=3),"ear_verif_subsistema_percentual":[70,65,72]})
    ena=pd.DataFrame({"ena_data":pd.date_range("2026-01-01",periods=3),"ena_bruta_regiao_percentualmlt":[90,120,70]})
    assert rank_events(event_candidates("max_ear_drop",ear_daily=ear),1).iloc[0]["value"]==5
    assert rank_events(event_candidates("ena_absolute_deviation",ena_daily=ena),1).iloc[0]["value"]==30

def test_net_load_definition_can_exclude_only_solar():
    data=hourly()
    solar_only=rank_events(event_candidates("min_net_load",hourly=data,net_load_mode="solar"),1,ascending=True)
    solar_wind=rank_events(event_candidates("min_net_load",hourly=data,net_load_mode="solar_wind"),1,ascending=True)
    assert solar_only.iloc[0]["value"] == solar_wind.iloc[0]["value"] + 10
