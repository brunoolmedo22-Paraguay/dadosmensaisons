"""Validação do processamento térmico disk-backed com dois meses grandes."""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from termicas_processing import process_thermal_files, release_thermal_cache
from termicas_lazy_panel import summarize_from_disk


def test_multimonth_lazy_disk_processing_and_aggregation(tmp_path):
    files = []
    for month in (1, 2):
        hours = pd.date_range(f"2026-{month:02}-01", periods=744 if month == 1 else 672, freq="h")
        # Cada hora tem 45 usinas distintas (mais de 25 mil registros/mês).
        frame = pd.DataFrame({
            "din_instante": hours.repeat(45),
            "nom_usina": [f"Usina {i:03}" for _ in range(len(hours)) for i in range(45)],
            "id_subsistema": "SE",
            "nom_subsistema": "Sudeste",
            "nom_combustivel": "Gás",
            "nom_tipopatamar": "Leve",
            "val_proggeracao": 10.0,
            "val_verifgeracao": 8.0,
            "val_progordemmerito": 6.0,
        })
        file = tmp_path / f"GERACAO_TERMICA_DESPACHO-2_2026_{month:02}.parquet"
        frame.to_parquet(file, index=False)
        files.append((file.name, file))
        del frame
    result = process_thermal_files(files)
    try:
        assert not result.errors, result.errors
        assert result.hourly.empty
        assert len(result.file_paths) == 2
        assert result.total_rows == (744 + 672) * 45
        assert result.bounds == (date(2026, 1, 1), date(2026, 2, 28))
        assert "val_verifgeracao" in result.metric_columns
        summary, ranking, rows, plants, hours, preview, output = summarize_from_disk(
            result, date(2026, 1, 1), date(2026, 2, 28),
            {}, "monthly", ["val_proggeracao", "val_verifgeracao"],
        )
        assert len(summary) == 2
        assert summary["Horas observadas"].tolist() == [744, 672]
        assert summary["val_proggeracao"].tolist() == pytest.approx([450, 450])
        assert summary["val_verifgeracao"].tolist() == pytest.approx([360, 360])
        assert rows == result.total_rows and plants == 45 and hours == 1416
        assert not ranking.empty and output is None
        assert preview.empty
        # Um filtro deve ser aplicado antes da média e preservar a semântica.
        part, *_ = summarize_from_disk(
            result, date(2026, 2, 1), date(2026, 2, 28),
            {"nom_usina": ["Usina 000", "Usina 001"]}, "monthly",
            ["val_proggeracao"],
        )
        assert part["val_proggeracao"].tolist() == pytest.approx([20])
    finally:
        release_thermal_cache(result)
    assert all(not p.exists() for p in result.file_paths)


def test_disk_export_preserves_all_original_columns(tmp_path):
    hours = pd.date_range("2026-01-01", periods=720, freq="h")
    data = pd.DataFrame({
        "din_instante": hours.repeat(40),
        "nom_usina": [f"U{i}" for _ in range(len(hours)) for i in range(40)],
        "id_subsistema": "SE",
        "nom_subsistema": "Sudeste",
        "nom_combustivel": "Gás",
        "val_proggeracao": 3.,
        "val_verifgeracao": 2.,
        "custom_ons_field": 12,
    })
    file=tmp_path/"GERACAO_TERMICA_DESPACHO-2_2026_01.parquet"
    data.to_parquet(file, index=False)
    result=process_thermal_files([(file.name,file)])
    try:
        summary, ranking, rows, plants, hours_count, preview, raw = summarize_from_disk(
            result,date(2026,1,1),date(2026,1,1),{},"daily",
            ["val_proggeracao"],raw_mode=True,
        )
        import gzip
        exported=pd.read_csv(__import__("io").BytesIO(gzip.decompress(raw)),sep=";")
        assert "custom_ons_field" in exported
        assert len(exported)==24*40
        assert len(preview)==24*40
    finally:
        release_thermal_cache(result)


def test_syntax_all_sources():
    root=Path(__file__).resolve().parents[1]
    for name in ("termicas_processing.py","termicas_panel.py","termicas_lazy_panel.py","app.py"):
        ast.parse((root/name).read_text("utf-8"))


def test_duckdb_concatenated_parquet_and_csv_preserve_all_rows_and_union_schema(tmp_path):
    import duckdb
    import gzip
    from io import BytesIO
    from termicas_duckdb import export_thermal
    sources = []
    for month in (1, 2):
        hours = pd.date_range(f"2026-{month:02}-01", periods=720, freq="h")
        frame = pd.DataFrame({
            "din_instante": hours.repeat(40),
            "nom_usina": [f"T{i:02d}" for _ in range(len(hours)) for i in range(40)],
            "id_subsistema": "SE", "nom_subsistema": "Sudeste",
            "val_proggeracao": 10.0, "val_verifgeracao": 9.0,
        })
        if month == 2:
            frame["campo_novo_ons"] = "NOVO"
        path=tmp_path/f"GERACAO_TERMICA_DESPACHO-2_2026_{month:02}.parquet"
        frame.to_parquet(path, index=False)
        sources.append((path.name,path))
    result = process_thermal_files(sources)
    try:
        assert len(result.file_paths)==2 and not result.errors, result.errors
        parquet = export_thermal(result,"parquet")
        with duckdb.connect() as conn:
            rows, nonnull = conn.execute(
                "SELECT COUNT(*), COUNT(campo_novo_ons) FROM read_parquet(?)",
                [str(parquet)],
            ).fetchone()
        assert rows == 2*720*40
        assert nonnull == 720*40
        csv = export_thermal(result,"csv.gz")
        with gzip.open(csv, "rt", encoding="utf-8-sig") as inp:
            head=inp.readline().strip()
            line_count=sum(1 for _ in inp)
        assert "campo_novo_ons" in head
        assert line_count == rows
    finally:
        release_thermal_cache(result)
