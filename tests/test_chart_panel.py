import ast
import html
import math
from datetime import date
from typing import Any
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
        self.assertIn("st.plotly_chart", self.source)
        self.assertIn("chart_subsystem_value", self.source)
        self.assertIn("chart_granularity_value", self.source)
        self.assertIn('mime="image/svg+xml"', self.source)
        self.assertIn('"chart_download_panel_svg"', self.source)
        self.assertIn('key="download_svg_full_panel"', self.source)

    def test_compact_grid_and_inline_controls(self) -> None:
        self.assertIn('chart_panel_columns = st.columns([0.95, 1.95], gap="small")', self.source)
        self.assertIn('config_columns = st.columns(2, gap="small")', self.source)
        self.assertIn('chart_date_columns = st.columns(2, gap="small")', self.source)
        self.assertIn('render_chart_controls_and_exports(', self.source)
        self.assertIn('build_combined_plotly_chart(', self.source)
        self.assertIn('st.plotly_chart(', self.source)
        self.assertNotIn("min-height: 31rem", self.source)

    def test_hover_line_is_synchronized_across_all_subplots(self) -> None:
        self.assertIn('hoversubplots="axis"', self.source)
        self.assertIn('hovermode="x"', self.source)
        self.assertIn('xaxis="x"', self.source)
        self.assertIn('"spikemode": "across"', self.source)
        self.assertNotIn('shared_xaxes=True', self.source)

    def test_hourly_is_chart_only_and_filters_non_hourly_sources(self) -> None:
        self.assertIn('CHART_GRANULARITIES', self.source)
        self.assertIn('"hourly",', self.source)
        self.assertIn('if granularity == "hourly" and source != "BALANCO"', self.source)
        self.assertIn('["BALANCO"]', self.source)
        self.assertIn('chart_granularity == "hourly"', self.source)


    def test_subsystem_changes_do_not_reset_date_state(self) -> None:
        self.assertIn('analysis_start_key = "analysis_start_date"', self.source)
        self.assertIn('analysis_end_key = "analysis_end_date"', self.source)
        self.assertIn('chart_start_key = f"chart_start_{chart_granularity}"', self.source)
        self.assertIn('chart_end_key = f"chart_end_{chart_granularity}"', self.source)
        self.assertNotIn('subsystem_slug(subsystem_key)}_{source_slug}_{granularity}', self.source)
        self.assertNotIn('subsystem_slug(chart_subsystem_key)}_{chart_granularity}', self.source)
        self.assertIn('preserve_date_state(', self.source)


class SvgChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        wanted = {
            "compact_number",
            "svg_time_ticks",
            "svg_canvas_width",
            "prepare_svg_series",
            "svg_line_chart",
            "svg_stacked_chart",
        }
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
            "date": date,
            "Any": Any,
            "SOURCE_LABELS": {
                "PT": {"BALANCO": "Balanço", "EAR": "EAR", "ENA": "ENA"}
            },
            "GRANULARITY_LABELS": {
                "PT": {
                    "hourly": "Horária",
                    "daily": "Diária",
                    "monthly": "Mensal",
                    "yearly": "Anual",
                }
            },
            "language": "PT",
            "ui_text": lambda key: "Painel de gráficos" if key == "charts_title" else key,
        }
        exec(compile(module, str(APP_PATH), "exec"), namespace)
        cls.svg_line_chart = staticmethod(namespace["svg_line_chart"])
        cls.svg_stacked_chart = staticmethod(namespace["svg_stacked_chart"])

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
        self.assertIn("03/26", svg)
        self.assertIn("ENA bruta (MWmed)", svg)
        self.assertIn('height="360"', svg)

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

    def test_long_period_svg_marks_every_year(self) -> None:
        years = list(range(2000, 2028))
        frame = pd.DataFrame(
            {
                "__period_start": pd.to_datetime([f"{year}-01-01" for year in years]),
                "ENA bruta (MWmed)": [float(year) for year in years],
            }
        )
        svg = self.svg_line_chart(
            frame,
            "ENA bruta (MWmed)",
            "monthly",
            "ENA — ENA bruta (MWmed)",
            "SIN · Mensal · 01/01/2000 a 31/12/2027",
            start_date=date(2000, 1, 1),
            end_date=date(2027, 12, 31),
        ).decode("utf-8")
        for year in years:
            self.assertIn(f">{year}</text>", svg)
        self.assertIn('width="1730"', svg)

    def test_stacked_svg_contains_all_selected_curves_and_shared_year_axis(self) -> None:
        dates = pd.to_datetime(["2000-01-01", "2004-01-01", "2007-01-01"])
        specs = []
        for source, metric, values in (
            ("BALANCO", "Carga (MWmed)", [100.0, 110.0, 105.0]),
            ("EAR", "EAR máxima (MWmês)", [50.0, 52.0, 51.0]),
            ("ENA", "ENA bruta (MWmed)", [80.0, 90.0, 85.0]),
        ):
            specs.append(
                {
                    "source": source,
                    "metric": metric,
                    "summary": pd.DataFrame(
                        {"__period_start": dates, metric: values}
                    ),
                }
            )
        svg = self.svg_stacked_chart(
            specs,
            "monthly",
            date(2000, 1, 1),
            date(2007, 12, 31),
            "SIN",
        ).decode("utf-8")
        self.assertIn("Balanço — Carga (MWmed)", svg)
        self.assertIn("EAR — EAR máxima (MWmês)", svg)
        self.assertIn("ENA — ENA bruta (MWmed)", svg)
        self.assertEqual(svg.count("<path"), 3)
        self.assertIn(">2000</text>", svg)
        self.assertIn(">2004</text>", svg)
        self.assertIn(">2007</text>", svg)


if __name__ == "__main__":
    unittest.main()
