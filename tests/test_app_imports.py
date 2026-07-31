from pathlib import Path
import unittest


class AppImportStrategyTests(unittest.TestCase):
    def test_app_does_not_force_reload_auxiliary_modules(self) -> None:
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("importlib.reload", app_source)
        self.assertNotIn("sys.modules.pop", app_source)

    def test_app_uses_parallel_source_pipeline(self) -> None:
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("run_parallel_sources", app_source)
        self.assertIn("max_workers=3", app_source)
        self.assertNotIn("for source_index", app_source)

    def test_app_uses_ena_csv_fallback_pipeline(self) -> None:
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_ena_download.download_ena_years", app_source)
        self.assertIn("_ena.process_data_files", app_source)
        self.assertIn("fallback CSV", app_source)


if __name__ == "__main__":
    unittest.main()


def test_app_uses_fresh_power_panel_module_name() -> None:
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "from power_panel_v2 import (" in source
    assert "from power_panel import (" not in source
    assert "use_container_width=True" not in source
