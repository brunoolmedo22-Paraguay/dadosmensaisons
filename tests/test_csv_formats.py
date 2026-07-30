from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from unified_ons import localize_table_numbers, serialize_unified_csv


def sample_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Data": [pd.Timestamp("2026-01-01").date()],
            "ENA bruta (MWmed)": [1234.56],
            "Cobertura ENA (%)": [100.0],
            "Status ENA": ["Completo"],
        }
    )


def test_csv_uses_semicolon_and_decimal_comma() -> None:
    content = serialize_unified_csv(
        sample_data(), separator=";", decimal=","
    ).decode("utf-8-sig")
    assert content.splitlines()[0] == "Data;ENA bruta (MWmed)"
    assert content.splitlines()[1] == "01/01/2026;1234,56"


def test_csv_includes_utf8_bom() -> None:
    assert serialize_unified_csv(
        sample_data(), separator=";", decimal=","
    ).startswith(b"\xef\xbb\xbf")


def test_csv_rejects_ambiguous_or_invalid_separators() -> None:
    with pytest.raises(ValueError):
        serialize_unified_csv(sample_data(), separator=",", decimal=",")
    with pytest.raises(ValueError):
        serialize_unified_csv(sample_data(), separator="|", decimal=",")


def test_table_numbers_use_decimal_comma() -> None:
    localized = localize_table_numbers(
        sample_data(),
        decimal_columns=["ENA bruta (MWmed)"],
        percentage_columns=["Cobertura ENA (%)"],
    )
    assert localized.loc[0, "ENA bruta (MWmed)"] == "1234,56"
    assert localized.loc[0, "Cobertura ENA (%)"] == "100,0%"


def test_app_offers_only_regional_csv_download() -> None:
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'ui_text("download_csv")' in source
    assert 'separator=";"' in source
    assert 'decimal=","' in source
    assert "download_csv_standard" not in source
    assert "download_csv_regional" not in source
    assert "_standard.csv" not in source
    assert "_regional.csv" not in source
