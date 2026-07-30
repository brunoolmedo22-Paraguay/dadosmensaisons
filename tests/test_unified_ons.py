from __future__ import annotations

import pandas as pd

from unified_ons import build_unified_csv_export, combine_summaries


def test_combines_balance_and_ear_on_same_daily_row() -> None:
    balance = pd.DataFrame(
        {
            "Data": [pd.Timestamp("2026-01-01").date()],
            "__period_start": [pd.Timestamp("2026-01-01")],
            "Horas com dados": [24],
            "Horas esperadas": [24],
            "Cobertura (%)": [100.0],
            "Status do período": ["Completo"],
            "Carga (MWmed)": [1000.0],
        }
    )
    ear = pd.DataFrame(
        {
            "Data": [pd.Timestamp("2026-01-01").date()],
            "__period_start": [pd.Timestamp("2026-01-01")],
            "Dias com dados": [1],
            "Dias esperados": [1],
            "Cobertura (%)": [100.0],
            "Status do período": ["Completo"],
            "EAR verificada (%)": [72.5],
        }
    )

    result, metrics, coverage, status = combine_summaries(
        balance,
        ear,
        granularity="daily",
        selected_sources=["BALANCO", "EAR"],
        balance_metrics=["Carga (MWmed)"],
        ear_metrics=["EAR verificada (%)"],
    )

    assert len(result) == 1
    assert result.loc[0, "Carga (MWmed)"] == 1000.0
    assert result.loc[0, "EAR verificada (%)"] == 72.5
    assert metrics == ["Carga (MWmed)", "EAR verificada (%)"]
    assert coverage == ["Cobertura Balanço (%)", "Cobertura EAR (%)"]
    assert status == ["Status Balanço", "Status EAR"]


def test_outer_merge_preserves_dates_from_each_source() -> None:
    balance = pd.DataFrame(
        {
            "__period_start": [pd.Timestamp("2026-01-01")],
            "Carga (MWmed)": [1000.0],
        }
    )
    ear = pd.DataFrame(
        {
            "__period_start": [pd.Timestamp("2026-01-02")],
            "EAR verificada (%)": [73.0],
        }
    )

    result, *_ = combine_summaries(
        balance,
        ear,
        granularity="daily",
        selected_sources=["BALANCO", "EAR"],
        balance_metrics=["Carga (MWmed)"],
        ear_metrics=["EAR verificada (%)"],
    )

    assert list(result["Data"].astype(str)) == ["2026-01-01", "2026-01-02"]


def test_csv_excludes_auxiliary_quality_columns() -> None:
    data = pd.DataFrame(
        {
            "Data": [pd.Timestamp("2026-01-01").date()],
            "__period_start": [pd.Timestamp("2026-01-01")],
            "Carga (MWmed)": [1000.0],
            "EAR verificada (%)": [72.5],
            "Horas com dados": [24],
            "Horas esperadas": [24],
            "Dias com dados": [1],
            "Dias esperados": [1],
            "Cobertura Balanço (%)": [100.0],
            "Cobertura EAR (%)": [100.0],
            "Status Balanço": ["Completo"],
            "Status EAR": ["Completo"],
        }
    )

    export = build_unified_csv_export(data)

    assert list(export.columns) == ["Data", "Carga (MWmed)", "EAR verificada (%)"]
    assert export.loc[0, "Data"] == "01/01/2026"
