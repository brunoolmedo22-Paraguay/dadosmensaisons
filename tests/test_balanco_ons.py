from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from balanco_ons import (
    CSV_EXPORT_COLUMNS,
    WorkbookError,
    available_subsystems,
    build_csv_export,
    build_granular_csv_export,
    build_period_summary,
    extract_year_from_filename,
    filter_hourly_by_subsystem,
    process_parquet_files,
    process_uploads,
)


def workbook_bytes(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Sheet1")
    return buffer.getvalue()


class ExtractYearTests(unittest.TestCase):
    def test_extracts_year(self) -> None:
        self.assertEqual(
            extract_year_from_filename("BALANCO_ENERGIA_SUBSISTEMA_2026.xlsx"),
            2026,
        )

    def test_rejects_missing_year(self) -> None:
        with self.assertRaises(WorkbookError):
            extract_year_from_filename("balanco.xlsx")

    def test_rejects_ambiguous_year(self) -> None:
        with self.assertRaises(WorkbookError):
            extract_year_from_filename("balanco_2025_2026.xlsx")


class ProcessingTests(unittest.TestCase):
    def test_retains_subsystems_and_calculates_sin_monthly_mean(self) -> None:
        frame = pd.DataFrame(
            {
                "id_subsistema": ["N", "SIN", "SIN", "SIN"],
                "nom_subsistema": [
                    "NORTE",
                    "SISTEMA INTERLIGADO NACIONAL",
                    "SISTEMA INTERLIGADO NACIONAL",
                    "SISTEMA INTERLIGADO NACIONAL",
                ],
                "din_instante": pd.to_datetime(
                    [
                        "2026-01-01 00:00",
                        "2026-01-01 00:00",
                        "2026-01-01 01:00",
                        "2026-02-01 00:00",
                    ]
                ),
                "val_gerhidraulica": [999.0, 100.0, 200.0, 300.0],
                "val_carga": [999.0, 500.0, 700.0, 900.0],
            }
        )
        result = process_uploads(
            [("BALANCO_ENERGIA_SUBSISTEMA_2026.xlsx", workbook_bytes(frame))]
        )

        self.assertFalse(result.errors)
        self.assertEqual(len(result.monthly), 2)
        january = result.monthly.loc[result.monthly["Mês nº"].eq(1)].iloc[0]
        self.assertEqual(january["Geração hidráulica (MWmed)"], 150.0)
        self.assertEqual(january["Carga (MWmed)"], 600.0)
        self.assertEqual(january["Horas com dados"], 2)
        self.assertEqual(len(result.hourly), 4)
        self.assertEqual(
            available_subsystems(result.hourly),
            [("SIN", "SIN"), ("N", "N · Norte")],
        )
        north = filter_hourly_by_subsystem(result.hourly, "N")
        self.assertEqual(len(north), 1)
        self.assertEqual(float(north.iloc[0]["val_carga"]), 999.0)

    def test_filename_year_is_validated_against_internal_dates(self) -> None:
        frame = pd.DataFrame(
            {
                "id_subsistema": ["SIN"],
                "din_instante": pd.to_datetime(["2025-01-01 00:00"]),
                "val_carga": [100.0],
            }
        )
        result = process_uploads(
            [("BALANCO_ENERGIA_SUBSISTEMA_2026.xlsx", workbook_bytes(frame))]
        )
        self.assertTrue(result.monthly.empty)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("o nome indica 2026", result.errors[0])

    def test_overlapping_files_do_not_double_count_hours(self) -> None:
        frame_a = pd.DataFrame(
            {
                "id_subsistema": ["SIN"],
                "din_instante": pd.to_datetime(["2026-01-01 00:00"]),
                "val_carga": [100.0],
            }
        )
        frame_b = pd.DataFrame(
            {
                "id_subsistema": ["SIN"],
                "din_instante": pd.to_datetime(["2026-01-01 00:00"]),
                "val_carga": [200.0],
            }
        )
        result = process_uploads(
            [
                ("balanco_a_2026.xlsx", workbook_bytes(frame_a)),
                ("balanco_b_2026.xlsx", workbook_bytes(frame_b)),
            ]
        )

        self.assertEqual(result.hourly_rows, 1)
        self.assertEqual(result.monthly.iloc[0]["Carga (MWmed)"], 200.0)
        self.assertTrue(any("sobreposto" in warning for warning in result.warnings))

    def test_builds_summary_for_selected_subsystem(self) -> None:
        frame = pd.DataFrame(
            {
                "id_subsistema": ["SIN", "N", "SIN", "N"],
                "nom_subsistema": [
                    "SISTEMA INTERLIGADO NACIONAL",
                    "NORTE",
                    "SISTEMA INTERLIGADO NACIONAL",
                    "NORTE",
                ],
                "din_instante": pd.to_datetime(
                    [
                        "2026-01-01 00:00",
                        "2026-01-01 00:00",
                        "2026-01-01 01:00",
                        "2026-01-01 01:00",
                    ]
                ),
                "val_carga": [100.0, 20.0, 200.0, 40.0],
            }
        )
        result = process_uploads(
            [("BALANCO_ENERGIA_SUBSISTEMA_2026.xlsx", workbook_bytes(frame))]
        )

        north_hourly = filter_hourly_by_subsystem(result.hourly, "N")
        north_monthly = build_period_summary(north_hourly, "monthly")

        self.assertEqual(len(north_hourly), 2)
        self.assertEqual(north_monthly.iloc[0]["Carga (MWmed)"], 30.0)

    def test_csv_export_contains_only_requested_columns(self) -> None:
        table = pd.DataFrame(
            {
                "Ano": [2026],
                "Mês nº": [1],
                "Mês": ["Janeiro"],
                "Período": ["2026-01"],
                "Horas com dados": [744],
                "Cobertura (%)": [100.0],
                "Geração hidráulica (MWmed)": [50_000.0],
                "Geração térmica (MWmed)": [9_000.0],
                "Geração eólica (MWmed)": [11_000.0],
                "Geração solar (MWmed)": [12_000.0],
                "Carga (MWmed)": [82_000.0],
                "Intercâmbio (MWmed)": [0.0],
            }
        )

        exported = build_csv_export(table)

        self.assertEqual(exported.columns.tolist(), CSV_EXPORT_COLUMNS)
        self.assertNotIn("Cobertura (%)", exported.columns)
        self.assertNotIn("Período", exported.columns)

    def test_processes_downloaded_parquet(self) -> None:
        frame = pd.DataFrame(
            {
                "id_subsistema": ["SIN", "SIN"],
                "din_instante": pd.to_datetime(
                    ["2026-03-01 00:00", "2026-03-01 01:00"]
                ),
                "val_gersolar": [1_000.0, 1_200.0],
                "val_carga": [80_000.0, 82_000.0],
            }
        )

        with TemporaryDirectory() as temporary_directory:
            path = (
                Path(temporary_directory)
                / "BALANCO_ENERGIA_SUBSISTEMA_2026.parquet"
            )
            frame.to_parquet(path, index=False)
            result = process_parquet_files([(path.name, path)])

        self.assertFalse(result.errors)
        self.assertEqual(len(result.monthly), 1)
        march = result.monthly.iloc[0]
        self.assertEqual(march["Geração solar (MWmed)"], 1_100.0)
        self.assertEqual(march["Carga (MWmed)"], 81_000.0)
        self.assertEqual(result.file_report.iloc[0]["Arquivo"], path.name)

    def test_builds_all_granularities_and_filters_dates(self) -> None:
        timestamps = pd.date_range(
            "2024-02-28 00:00",
            periods=48,
            freq="h",
        )
        hourly = pd.DataFrame(
            {
                "din_instante": timestamps,
                "val_carga": list(range(48)),
                "val_gersolar": [100.0] * 48,
            }
        )

        hourly_summary = build_period_summary(
            hourly,
            granularity="hourly",
            start_date=pd.Timestamp("2024-02-28"),
            end_date=pd.Timestamp("2024-02-28"),
        )
        daily_summary = build_period_summary(hourly, granularity="daily")
        monthly_summary = build_period_summary(hourly, granularity="monthly")
        yearly_summary = build_period_summary(hourly, granularity="yearly")

        self.assertEqual(len(hourly_summary), 24)
        self.assertEqual(len(daily_summary), 2)
        self.assertEqual(
            daily_summary.iloc[0]["Carga (MWmed)"],
            11.5,
        )
        self.assertEqual(len(monthly_summary), 1)
        self.assertEqual(monthly_summary.iloc[0]["Horas esperadas"], 696)
        self.assertEqual(monthly_summary.iloc[0]["Status do período"], "Parcial")
        self.assertEqual(len(yearly_summary), 1)
        self.assertEqual(yearly_summary.iloc[0]["Horas esperadas"], 8_784)

    def test_granular_csv_matches_selected_discretization(self) -> None:
        daily = pd.DataFrame(
            {
                "Data": [pd.Timestamp("2026-07-28").date()],
                "Carga (MWmed)": [80_000.0],
                "Cobertura (%)": [100.0],
            }
        )

        exported = build_granular_csv_export(daily, "daily")

        self.assertEqual(exported.columns[0], "Data")
        self.assertEqual(exported.iloc[0]["Data"], "28/07/2026")
        self.assertNotIn("Cobertura (%)", exported.columns)
        self.assertIn("Geração hidráulica (MWmed)", exported.columns)


if __name__ == "__main__":
    unittest.main()
