from __future__ import annotations

from pathlib import Path

import pandas as pd

import ena_processing as ep


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_subsistema": [
                "SE", "S", "NE", "N",
                "SE", "S", "NE", "N",
            ],
            "nom_subsistema": [
                "Sudeste/Centro-Oeste", "Sul", "Nordeste", "Norte",
                "Sudeste/Centro-Oeste", "Sul", "Nordeste", "Norte",
            ],
            "ena_data": pd.to_datetime(
                ["2026-01-01"] * 4 + ["2026-01-02"] * 4
            ),
            "ena_bruta_regiao_mwmed": [
                100.0, 50.0, 20.0, 10.0,
                120.0, 60.0, 24.0, 12.0,
            ],
            "ena_bruta_regiao_percentualmlt": [
                50.0, 100.0, 100.0, 50.0,
                60.0, 120.0, 120.0, 60.0,
            ],
            "ena_armazenavel_regiao_mwmed": [
                80.0, 40.0, 16.0, 8.0,
                90.0, 45.0, 18.0, 9.0,
            ],
            "ena_armazenavel_regiao_percentualmlt": [
                40.0, 80.0, 80.0, 40.0,
                45.0, 90.0, 90.0, 45.0,
            ],
        }
    )


def test_loads_official_columns_and_builds_sin(monkeypatch) -> None:
    monkeypatch.setattr(pd, "read_parquet", lambda path: sample_frame())
    result = ep.process_parquet_files(
        [("ENA_DIARIO_SUBSISTEMA_2026.parquet", Path("unused.parquet"))]
    )
    assert not result.errors
    assert {key for key, _ in ep.available_subsystems(result.daily)} == {"SIN", "SE", "S", "NE", "N"}
    sin = result.daily.loc[
        result.daily["__subsystem_key"].eq("SIN")
        & result.daily["ena_data"].eq(pd.Timestamp("2026-01-01"))
    ].iloc[0]
    assert sin["ena_bruta_regiao_mwmed"] == 180.0
    # MLT inferida: 100/0,5 + 50/1 + 20/1 + 10/0,5 = 290.
    assert round(float(sin["ena_bruta_regiao_percentualmlt"]), 6) == round(180 / 290 * 100, 6)
    assert bool(sin["__sin_calculated"]) is True
    assert sin["__subsystem_label"] == "SIN · ENA calculada"


def test_does_not_build_sin_without_all_four_subsystems(monkeypatch) -> None:
    incomplete = sample_frame().loc[lambda frame: frame["id_subsistema"].ne("N")].copy()
    monkeypatch.setattr(pd, "read_parquet", lambda path: incomplete)
    result = ep.process_parquet_files(
        [("ENA_DIARIO_SUBSISTEMA_2026.parquet", Path("unused.parquet"))]
    )
    assert not result.errors
    assert not result.daily["__subsystem_key"].eq("SIN").any()


def test_does_not_build_sin_with_invalid_mlt_input(monkeypatch) -> None:
    invalid = sample_frame().copy()
    invalid.loc[
        invalid["id_subsistema"].eq("N"),
        "ena_bruta_regiao_percentualmlt",
    ] = 0.0
    monkeypatch.setattr(pd, "read_parquet", lambda path: invalid)
    result = ep.process_parquet_files(
        [("ENA_DIARIO_SUBSISTEMA_2026.parquet", Path("unused.parquet"))]
    )
    assert not result.errors
    assert not result.daily["__subsystem_key"].eq("SIN").any()


def test_preserves_official_sin_without_marking_it_calculated(monkeypatch) -> None:
    official = sample_frame().copy()
    official_row = official.iloc[[0]].copy()
    official_row["id_subsistema"] = "SIN"
    official_row["nom_subsistema"] = "SIN"
    official_row["ena_bruta_regiao_mwmed"] = 999.0
    official_row["ena_data"] = pd.Timestamp("2026-01-01")
    official = pd.concat([official, official_row], ignore_index=True)
    monkeypatch.setattr(pd, "read_parquet", lambda path: official)
    result = ep.process_parquet_files(
        [("ENA_DIARIO_SUBSISTEMA_2026.parquet", Path("unused.parquet"))]
    )
    sin_day = result.daily.loc[
        result.daily["__subsystem_key"].eq("SIN")
        & result.daily["ena_data"].eq(pd.Timestamp("2026-01-01"))
    ]
    assert len(sin_day) == 1
    assert sin_day.iloc[0]["ena_bruta_regiao_mwmed"] == 999.0
    assert bool(sin_day.iloc[0]["__sin_calculated"]) is False


def test_monthly_summary_and_quality_columns() -> None:
    daily = sample_frame().loc[
        lambda frame: frame["id_subsistema"].eq("SE")
    ].assign(
        __subsystem_key="SE",
        __subsystem_label="Sudeste/Centro-Oeste",
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
