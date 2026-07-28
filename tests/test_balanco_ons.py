from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import pandas as pd

from balanco_ons import (
    CSV_EXPORT_COLUMNS,
    WorkbookError,
    build_csv_export,
    extract_year_from_filename,
    process_files,
    process_paths,
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
    def test_filters_sin_and_calculates_monthly_mean(self) -> None:
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


class FormatTests(unittest.TestCase):
    def sample_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id_subsistema": ["SIN", "SIN", "N"],
                "din_instante": [
                    "2024-01-01 00:00:00",
                    "2024-01-01 01:00:00",
                    "2024-01-01 00:00:00",
                ],
                "val_gerhidraulica": [100.0, 200.0, 999.0],
                "val_carga": [500.0, 700.0, 999.0],
            }
        )

    def test_reads_parquet(self) -> None:
        buffer = BytesIO()
        self.sample_frame().to_parquet(buffer, index=False)
        result = process_files(
            [("BALANCO_ENERGIA_SUBSISTEMA_2024.parquet", buffer.getvalue())]
        )

        self.assertFalse(result.errors)
        self.assertEqual(result.hourly_rows, 2)
        self.assertEqual(
            result.monthly.iloc[0]["Geração hidráulica (MWmed)"], 150.0
        )

    def test_reads_semicolon_csv(self) -> None:
        content = self.sample_frame().to_csv(index=False, sep=";").encode("utf-8")
        result = process_files(
            [("BALANCO_ENERGIA_SUBSISTEMA_2024.csv", content)]
        )

        self.assertFalse(result.errors)
        self.assertEqual(result.monthly.iloc[0]["Carga (MWmed)"], 600.0)

    def test_reads_comma_csv_with_decimal_comma(self) -> None:
        content = (
            "id_subsistema,din_instante,val_carga\n"
            "SIN,2024-01-01 00:00:00,\"1.500,50\"\n"
        ).encode("utf-8")
        result = process_files(
            [("BALANCO_ENERGIA_SUBSISTEMA_2024.csv", content)]
        )

        self.assertFalse(result.errors)
        self.assertAlmostEqual(result.monthly.iloc[0]["Carga (MWmed)"], 1500.5)

    def test_rejects_unsupported_extension(self) -> None:
        result = process_files([("BALANCO_2024.json", b"{}")])
        self.assertTrue(result.errors)
        self.assertIn("extensão não suportada", result.errors[0])

    def test_process_paths_reads_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "BALANCO_ENERGIA_SUBSISTEMA_2024.csv"
            path.write_text(
                self.sample_frame().to_csv(index=False, sep=";"),
                encoding="utf-8",
            )
            result = process_paths([path])

        self.assertFalse(result.errors)
        self.assertEqual(result.hourly_rows, 2)


if __name__ == "__main__":
    unittest.main()
