"""Testes regressivos da nova fonte térmica (sem depender da rede do ONS)."""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

import termicas_download as download
from termicas_processing import aggregate_thermal, process_thermal_files


def test_ons_catalog_resource_names_and_host_filter():
    yearly = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/geracao_termica_despacho_2_ho/GERACAO_TERMICA_DESPACHO_2021.parquet"
    monthly = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/geracao_termica_despacho_2_ho/GERACAO_TERMICA_DESPACHO-2_2026_01.xlsx"
    assert download._resource(yearly) == (2021, None, "parquet")
    assert download._resource(monthly) is None  # XLSX não usado como transporte preferencial.
    assert download._resource(monthly.replace(".xlsx", ".csv")) == (2026, 1, "csv")
    assert download._resource(yearly.replace("ons-aws-prod-opendata.s3.amazonaws.com", "evil.example.org")) is None


def test_discover_resources_from_catalog_html():
    class Response:
        text = (
            '<a href="https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/'
            'geracao_termica_despacho_2_ho/GERACAO_TERMICA_DESPACHO_2021.parquet">2021</a>'
            '<a href="https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/'
            'geracao_termica_despacho_2_ho/GERACAO_TERMICA_DESPACHO-2_2022_01.csv">jan 2022</a>'
        )
        def raise_for_status(self): pass
        def close(self): pass

    class Session:
        def get(self, *args, **kwargs): return Response()

    resources = download.discover_resources(session=Session())
    assert (2021, None) in resources
    assert (2022, 1) in resources


def test_prefers_monthly_2022_and_parquet_then_csv_fallback(tmp_path, monkeypatch):
    prefix = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/geracao_termica_despacho_2_ho/"
    catalog = {
        (2022, None): {"parquet": prefix + "GERACAO_TERMICA_DESPACHO_2022.parquet"},
        (2022, 1): {"parquet": prefix + "GERACAO_TERMICA_DESPACHO-2_2022_01.parquet",
                    "csv": prefix + "GERACAO_TERMICA_DESPACHO-2_2022_01.csv"},
        (2022, 2): {"parquet": prefix + "GERACAO_TERMICA_DESPACHO-2_2022_02.parquet"},
    }
    monkeypatch.setattr(download, "discover_resources", lambda _session: catalog)
    attempted = []
    def mock_one(http, url, target, fmt):
        attempted.append((target.name, fmt))
        if "_01.parquet" in url:
            raise download.ThermalDownloadError("parquet off")
        target.write_bytes(b"ok")
        return 2
    monkeypatch.setattr(download, "_download_one", mock_one)
    got = download.download_thermal_years([2022], tmp_path)
    assert len(got.files) == 2
    assert got.total_bytes == 4
    assert not got.errors
    assert [fmt for name, fmt in attempted] == ["parquet", "csv", "parquet"]
    assert not any(name == "GERACAO_TERMICA_DESPACHO_2022.parquet" for name, fmt in attempted)


def _records():
    return pd.DataFrame([
        {"din_instante": "2026-01-01 00:00:00", "nom_usina": "A", "id_subsistema": "SE",
         "val_proggeracao": 10, "val_verifgeracao": 8, "val_progordemmerito": 10,
         "din_publicacao": "2026-01-02 00:00:00"},
        {"din_instante": "2026-01-01 00:00:00", "nom_usina": "B", "id_subsistema": "SE",
         "val_proggeracao": 20, "val_verifgeracao": 18, "val_progordemmerito": 20,
         "din_publicacao": "2026-01-02 00:00:00"},
        {"din_instante": "2026-01-01 01:00:00", "nom_usina": "A", "id_subsistema": "SE",
         "val_proggeracao": 40, "val_verifgeracao": 39, "val_progordemmerito": 40,
         "din_publicacao": "2026-01-02 00:00:00"},
    ])


def test_aggregation_sum_by_hour_then_average_by_period(tmp_path):
    data = _records()
    file = tmp_path / "sample.parquet"
    data.to_parquet(file)
    result = process_thermal_files([(file.name, file)])
    assert not result.errors
    assert len(result.hourly) == 3
    daily = aggregate_thermal(result.hourly, "daily", ["val_proggeracao", "val_verifgeracao"])
    assert len(daily) == 1
    assert daily.loc[0, "Horas observadas"] == 2
    assert daily.loc[0, "val_proggeracao"] == pytest.approx(35.0)  # (10+20+40)/2
    assert daily.loc[0, "val_verifgeracao"] == pytest.approx(32.5)
    hourly = aggregate_thermal(result.hourly, "hourly", ["val_proggeracao"])
    assert hourly["val_proggeracao"].tolist() == [30, 40]


def test_latest_publication_wins_and_original_columns_preserved(tmp_path):
    data = pd.concat([_records(), _records().iloc[[0]]], ignore_index=True)
    data.loc[3, "din_publicacao"] = "2026-01-03 00:00:00"
    data.loc[3, "val_proggeracao"] = 12
    data["ceg"] = ["a", "b", "a", "a"]
    file = tmp_path / "with_edits.parquet"
    data.to_parquet(file)
    result = process_thermal_files([(file.name, file)])
    assert len(result.hourly) == 3
    assert result.warnings
    assert "ceg" in result.hourly.columns
    hourly = aggregate_thermal(result.hourly, "hourly", ["val_proggeracao"])
    assert hourly.iloc[0]["val_proggeracao"] == 32


def test_python_files_parse_without_syntax_errors():
    root = Path(__file__).resolve().parents[1]
    for name in ("app.py", "termicas_download.py", "termicas_processing.py", "termicas_panel.py"):
        ast.parse((root / name).read_text(encoding="utf-8"), filename=name)
