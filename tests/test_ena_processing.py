from __future__ import annotations

from pathlib import Path

import pandas as pd

import ena_processing as ep


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_subsistema": ["SE", "S", "SE", "S"],
            "nom_subsistema": ["Sudeste/Centro-Oeste", "Sul", "Sudeste/Centro-Oeste", "Sul"],
            "ena_data": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02"]),
            "ena_bruta_regiao_mwmed": [100.0, 50.0, 120.0, 60.0],
            "ena_bruta_regiao_percentualmlt": [50.0, 100.0, 60.0, 120.0],
            "ena_armazenavel_regiao_mwmed": [80.0, 40.0, 90.0, 45.0],
            "ena_armazenavel_regiao_percentualmlt": [40.0, 80.0, 45.0, 90.0],
        }
    )


def test_loads_official_columns_and_builds_sin(monkeypatch) -> None:
    monkeypatch.setattr(pd, "read_parquet", lambda path: sample_frame())
    result = ep.process_parquet_files(
        [("ENA_DIARIO_SUBSISTEMA_2026.parquet", Path("unused.parquet"))]
    )
    assert not result.errors
    assert {key for key, _ in ep.available_subsystems(result.daily)} == {"SIN", "SE", "S"}
    sin = result.daily.loc[
        result.daily["__subsystem_key"].eq("SIN")
        & result.daily["ena_data"].eq(pd.Timestamp("2026-01-01"))
    ].iloc[0]
    assert sin["ena_bruta_regiao_mwmed"] == 150.0
    # MLT regional inferida: 100/0,5 + 50/1,0 = 250; SIN = 150/250 = 60%.
    assert round(float(sin["ena_bruta_regiao_percentualmlt"]), 6) == 60.0


def test_monthly_summary_and_quality_columns() -> None:
    daily = sample_frame().assign(
        __subsystem_key=["SE", "S", "SE", "S"],
        __subsystem_label=["Sudeste/Centro-Oeste", "Sul", "Sudeste/Centro-Oeste", "Sul"],
        __file_order=0,
    )
    se = ep.filter_daily_by_subsystem(daily, "SE")
    summary = ep.build_period_summary(se, "monthly")
    assert len(summary) == 1
    assert summary.loc[0, "ENA bruta (MWmed)"] == 110.0
    assert summary.loc[0, "Dias com dados"] == 2
    assert summary.loc[0, "Dias esperados"] == 31
    assert summary.loc[0, "Status do período"] == "Parcial"


def test_csv_export_preserves_only_period_and_metrics() -> None:
    data = pd.DataFrame(
        {
            "Data": [pd.Timestamp("2026-01-01").date()],
            "ENA bruta (MWmed)": [100.0],
            "ENA bruta (% MLT)": [80.0],
            "ENA armazenável (MWmed)": [90.0],
            "ENA armazenável (% MLT)": [72.0],
            "Cobertura (%)": [100.0],
        }
    )
    export = ep.build_granular_csv_export(data, "daily")
    assert list(export.columns) == [
        "Data",
        "ENA bruta (MWmed)",
        "ENA bruta (% MLT)",
        "ENA armazenável (MWmed)",
        "ENA armazenável (% MLT)",
    ]
    assert export.loc[0, "Data"] == "01/01/2026"
