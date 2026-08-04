from datetime import date
import pandas as pd
import pytest
from ramp_panel import prepare_ramps, annual_severity, annual_distribution, hourly_heatmap, ramp_kpis


def sample():
    return pd.DataFrame({
        "din_instante": pd.to_datetime(["2024-01-01 00:00","2024-01-01 01:00","2024-01-01 03:00","2025-01-01 00:00","2025-01-01 01:00"]),
        "val_carga":[100,120,200,100,150],"val_gersolar":[0,10,20,0,10],"val_gereolica":[10,10,10,10,20]
    })

def test_consecutive_only_and_net_series():
    r=prepare_ramps(sample(),series="net_solar_wind",unit="mw")
    assert len(r)==2
    assert r.iloc[0]["ramp"]==10
    assert r.iloc[1]["ramp"]==30

def test_normalized_ramp():
    r=prepare_ramps(sample(),series="load",unit="percent")
    assert r.iloc[0]["ramp"]==pytest.approx(20)

def test_statistics_and_heatmap():
    r=prepare_ramps(sample())
    assert not annual_severity(r).empty
    assert set(annual_distribution(r).columns)=={"year","p05","p25","p50","p75","p95"}
    assert 1 in hourly_heatmap(r,"maximum").columns
    assert ramp_kpis(r).max_up==50
