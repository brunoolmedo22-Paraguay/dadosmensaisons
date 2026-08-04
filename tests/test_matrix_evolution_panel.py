import pandas as pd
import pytest
from matrix_evolution_panel import annual_matrix, matrix_kpis, first_threshold_year


def sample():
    frames=[]
    for year,solar,wind in [(2024,5,10),(2025,10,20)]:
        times=pd.date_range(f"{year}-01-01",periods=24,freq="h")
        frames.append(pd.DataFrame({"din_instante":times,"val_gerhidraulica":50,"val_gertermica":20,"val_gereolica":wind,"val_gersolar":solar,"val_carga":100,"val_intercambio":0}))
    return pd.concat(frames,ignore_index=True)

def test_annual_metrics_shares_growth_index():
    a=annual_matrix(sample(),base_year=2024)
    assert len(a)==2
    shares=a.loc[0,["share_hydro","share_thermal","share_wind","share_solar"]].sum()
    assert shares==pytest.approx(100)
    assert a.loc[1,"growth_solar"]==pytest.approx(100)
    assert a.loc[1,"index_solar"]==pytest.approx(200)

def test_kpis_and_threshold():
    a=annual_matrix(sample(),base_year=2024)
    assert matrix_kpis(a)["fastest_source"] in {"solar","wind"}
    assert first_threshold_year(a,"solar",5)==2024

def test_energy_measure_and_cumulative_growth():
    a=annual_matrix(sample(),base_year=2024,measure="energy")
    assert a.loc[0,"val_gersolar"] == pytest.approx(5*24/1000)
    assert a.loc[1,"cumulative_solar"] == pytest.approx(100)
