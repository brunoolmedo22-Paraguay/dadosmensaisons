import ast
import html
import math
from pathlib import Path
import unittest

import pandas as pd


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class ChartPanelStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")

    def test_chart_panel_is_independent_and_processed_files_are_last(self) -> None:
        chart_position = self.source.index('key="charts_panel"')
        processed_position = self.source.index('key="processed_files_panel"')
        self.assertLess(chart_position, processed_position)
        self.assertNotIn("st.line_chart", self.source)
        self.assertIn("chart_subsystem_value", self.source)
        self.assertIn("chart_granularity_value", self.source)
        self.assertIn('mime="image/svg+xml"', self.source)

    def test_compact_grid_and_inline_controls(self) -> None:
        self.assertIn('first_chart_row = st.columns(2, gap="small")', self.source)
        self.assertIn('second_chart_row = st.columns(2, gap="small")', self.source)
        self.assertIn('control_columns = st.columns([1.42, 1]', self.source)
        self.assertIn('config_columns = st.columns(2, gap="small")', self.source)
        self.assertIn('chart_date_columns = st.columns(2, gap="small")', self.source)
        self.assertNotIn("min-height: 31rem", self.source)

    def test_hourly_is_chart_only_and_filters_non_hourly_sources(self) -> None:
        self.assertIn('CHART_GRANULARITIES', self.source)
        self.assertIn('"hourly",', self.source)
        self.assertIn('if granularity == "hourly" and source != "BALANCO"', self.source)
        self.assertIn('["BALANCO"]', self.source)
        self.assertIn('chart_granularity == "hourly"', self.source)


class SvgChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        wanted = {"compact_number", "chart_x_label", "svg_line_chart"}
        nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in wanted
        ]
        module = ast.Module(body=nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {
            "pd": pd,
            "math": math,
            "html": html,
            "Granularity": str,
            "ChartGranularity": str,
        }
        exec(compile(module, str(APP_PATH), "exec"), namespace)
        cls.svg_line_chart = staticmethod(namespace["svg_line_chart"])

    def test_svg_contains_vector_path_and_labels(self) -> None:
        frame = pd.DataFrame(
            {
                "__period_start": pd.to_datetime(
                    ["2026-01-01", "2026-02-01", "2026-03-01"]
                ),
                "ENA bruta (MWmed)": [100.0, 150.0, 125.0],
            }
        )
        svg = self.svg_line_chart(
            frame,
            "ENA bruta (MWmed)",
            "monthly",
            "ENA — ENA bruta (MWmed)",
            "SIN · Mensual · 01/01/2026 a 31/03/2026",
        ).decode("utf-8")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("<path", svg)
        self.assertIn("#006b70", svg)
        self.assertIn("03/2026", svg)
        self.assertIn("ENA bruta (MWmed)", svg)
        self.assertIn('height="330"', svg)

    def test_hourly_svg_uses_hour_labels(self) -> None:
        frame = pd.DataFrame(
            {
                "__period_start": pd.to_datetime(
                    ["2026-01-01 00:00", "2026-01-01 01:00", "2026-01-01 02:00"]
                ),
                "Carga (MWmed)": [100.0, 110.0, 105.0],
            }
        )
        svg = self.svg_line_chart(
            frame,
            "Carga (MWmed)",
            "hourly",
            "Balanço — Carga (MWmed)",
            "SIN · Horária · 01/01/2026 a 01/01/2026",
        ).decode("utf-8")
        self.assertIn("01/01 00h", svg)
        self.assertIn("01/01 02h", svg)


if __name__ == "__main__":
    unittest.main()
