from __future__ import annotations

from pathlib import Path

import pandas as pd

import ear_processing as ep


def sample_frame() -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2024-01-01", "2024-01-03", freq="D"):
        for key, label, maximum, verified in [
            ("SE", "Sudeste/Centro-Oeste", 200.0, 100.0),
            ("S", "Sul", 100.0, 60.0),
            ("NE", "Nordeste", 80.0, 40.0),
            ("N", "Norte", 20.0, 10.0),
        ]:
            rows.append(
                {
                    "id_subsistema": key,
                    "nom_subsistema": label,
                    "ear_data": day,
                    "ear_max_subsistema": maximum,
                    "ear_verif_subsistema_mwmes": verified,
                    "ear_verif_subsistema_percentual": verified / maximum * 100,
                }
            )
    return pd.DataFrame(rows)


def test_process_parquet_builds_sin(monkeypatch, tmp_path: Path) -> None:
    frame = sample_frame()
    monkeypatch.setattr(pd, "read_parquet", lambda _: frame.copy())
    result = ep.process_parquet_files(
        [("EAR_DIARIO_SUBSISTEMA_2024.parquet", tmp_path / "sample.parquet")]
    )

    assert not result.errors
    options = dict(ep.available_subsystems(result.daily))
    assert list(options)[0] == "SIN"
    sin = ep.filter_daily_by_subsystem(result.daily, "SIN")
    assert len(sin) == 3
    assert sin.iloc[0]["ear_max_subsistema"] == 400.0
    assert sin.iloc[0]["ear_verif_subsistema_mwmes"] == 210.0
    assert round(float(sin.iloc[0]["ear_verif_subsistema_percentual"]), 2) == 52.5


def test_daily_monthly_yearly_summaries(monkeypatch, tmp_path: Path) -> None:
    frame = sample_frame()
    monkeypatch.setattr(pd, "read_parquet", lambda _: frame.copy())
    result = ep.process_parquet_files(
        [("EAR_DIARIO_SUBSISTEMA_2024.parquet", tmp_path / "sample.parquet")]
    )
    sin = ep.filter_daily_by_subsystem(result.daily, "SIN")

    daily = ep.build_period_summary(sin, "daily")
    monthly = ep.build_period_summary(sin, "monthly")
    yearly = ep.build_period_summary(sin, "yearly")

    assert len(daily) == 3
    assert daily["Dias esperados"].tolist() == [1, 1, 1]
    assert len(monthly) == 1
    assert monthly.iloc[0]["Mês"] == "Janeiro"
    assert monthly.iloc[0]["Dias esperados"] == 31
    assert len(yearly) == 1
    assert yearly.iloc[0]["Dias esperados"] == 366


def test_csv_export_preserves_technical_metric_names() -> None:
    data = pd.DataFrame(
        {
            "Data": [pd.Timestamp("2024-01-01").date()],
            "EAR máxima (MWmês)": [400.0],
            "EAR verificada (MWmês)": [210.0],
            "EAR verificada (%)": [52.5],
            "Cobertura (%)": [100.0],
        }
    )
    export = ep.build_granular_csv_export(data, "daily")
    assert export.columns.tolist() == [
        "Data",
        "EAR máxima (MWmês)",
        "EAR verificada (MWmês)",
        "EAR verificada (%)",
    ]
    assert export.iloc[0]["Data"] == "01/01/2024"


def test_extract_year_rejects_ambiguous_name() -> None:
    try:
        ep.extract_year_from_filename("EAR_2023_2024.parquet")
    except ep.WorkbookError:
        pass
    else:
        raise AssertionError("Expected WorkbookError")
