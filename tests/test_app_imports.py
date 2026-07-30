from pathlib import Path
import unittest


class AppImportStrategyTests(unittest.TestCase):
    def test_app_does_not_force_reload_auxiliary_modules(self) -> None:
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("importlib.reload", app_source)
        self.assertNotIn("sys.modules.pop", app_source)

    def test_app_uses_ena_csv_fallback_pipeline(self) -> None:
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_ena_download.download_ena_years", app_source)
        self.assertIn("_ena.process_data_files", app_source)
        self.assertIn("fallback CSV", app_source)


if __name__ == "__main__":
    unittest.main()
