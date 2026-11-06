"""Smoke tests de renderização Streamlit, sem tráfego externo."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from termicas_processing import process_thermal_files


def test_app_home_renders_without_data():
    app = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(str(app), default_timeout=45).run()
    assert not at.exception, [e.message for e in at.exception]


def test_thermal_panel_with_synthetic_hourly_data(tmp_path):
    from termicas_panel import render_thermal_panel
    data = pd.DataFrame([
        {"din_instante": "2026-01-01 00:00:00", "nom_usina": "A",
         "nom_subsistema": "Sudeste/Centro-Oeste", "id_subsistema": "SE",
         "nom_tipocombustivel": "Gás", "nom_tipopatamar": "Leve",
         "val_proggeracao": 10, "val_verifgeracao": 8},
        {"din_instante": "2026-01-01 01:00:00", "nom_usina": "B",
         "nom_subsistema": "Sudeste/Centro-Oeste", "id_subsistema": "SE",
         "nom_tipocombustivel": "Óleo", "nom_tipopatamar": "Leve",
         "val_proggeracao": 20, "val_verifgeracao": 22},
    ])
    filepath = tmp_path / "mock.csv"
    data.to_csv(filepath, index=False, sep=";")
    result = process_thermal_files([("mock.csv", filepath)])
    assert not result.errors
    # AppTest.from_function executa em outro módulo; não captura closures locais.
    def page():
        import pandas as pd
        from termicas_panel import render_thermal_panel
        from termicas_processing import ThermalResult
        frame = pd.DataFrame([
            {"din_instante": "2026-01-01 00:00:00", "nom_usina": "A",
             "nom_subsistema": "Sudeste", "id_subsistema": "SE",
             "nom_tipocombustivel": "Gás", "nom_tipopatamar": "Leve",
             "val_proggeracao": 10, "val_verifgeracao": 8},
            {"din_instante": "2026-01-01 01:00:00", "nom_usina": "B",
             "nom_subsistema": "Sudeste", "id_subsistema": "SE",
             "nom_tipocombustivel": "Óleo", "nom_tipopatamar": "Leve",
             "val_proggeracao": 20, "val_verifgeracao": 22},
        ])
        frame["din_instante"] = pd.to_datetime(frame["din_instante"])
        result = ThermalResult(
            hourly=frame, metric_columns=["val_proggeracao", "val_verifgeracao"],
            file_report=pd.DataFrame(), errors=[], warnings=[],
        )
        render_thermal_panel(result, "PT")
    at = AppTest.from_function(page, default_timeout=35).run()
    assert not at.exception, [e.message for e in at.exception]
