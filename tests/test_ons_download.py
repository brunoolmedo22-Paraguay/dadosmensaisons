from __future__ import annotations

import http.server
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

import ons_download
from ons_download import RemoteResource


class YearParsingTests(unittest.TestCase):
    def test_reads_single_year(self) -> None:
        self.assertEqual(
            ons_download.year_from_text("BALANCO_ENERGIA_SUBSISTEMA_2024"),
            2024,
        )

    def test_rejects_ambiguous_text(self) -> None:
        self.assertIsNone(ons_download.year_from_text("balanco_2024_2025"))

    def test_rejects_text_without_year(self) -> None:
        self.assertIsNone(ons_download.year_from_text("balanco"))


class TargetBuildingTests(unittest.TestCase):
    def test_portal_resource_comes_before_default_url(self) -> None:
        resources = [
            RemoteResource(
                year=2024,
                url="https://exemplo/BALANCO_ENERGIA_SUBSISTEMA_2024.parquet",
                extension="parquet",
                origin="portal",
            )
        ]
        targets = ons_download.build_targets([2024], resources, ("parquet", "csv"))

        self.assertEqual(targets[2024][0].origin, "portal")
        self.assertEqual(targets[2024][0].extension, "parquet")
        self.assertEqual(targets[2024][-1].extension, "csv")
        self.assertTrue(
            any(item.origin == "padrão" for item in targets[2024]),
            "o endereço padrão deve permanecer como alternativa",
        )

    def test_format_preference_is_respected(self) -> None:
        targets = ons_download.build_targets([2023], [], ("csv", "parquet"))
        self.assertEqual(
            [item.extension for item in targets[2023]],
            ["csv", "parquet"],
        )

    def test_missing_year_falls_back_to_default_pattern(self) -> None:
        targets = ons_download.build_targets([2019], [], ("parquet",))
        self.assertEqual(targets[2019][0].origin, "padrão")
        self.assertIn("BALANCO_ENERGIA_SUBSISTEMA_2019.parquet", targets[2019][0].url)


class DownloadTests(unittest.TestCase):
    """Usa um servidor HTTP local para validar o laço de download."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.served = tempfile.TemporaryDirectory()
        root = Path(cls.served.name)
        (root / "BALANCO_ENERGIA_SUBSISTEMA_2024.csv").write_text(
            "id_subsistema;din_instante;val_carga\nSIN;2024-01-01 00:00:00;100\n",
            encoding="utf-8",
        )

        handler = _handler_for(root)
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.served.cleanup()

    def _resource(self, year: int, extension: str) -> RemoteResource:
        return RemoteResource(
            year=year,
            url=(
                f"http://127.0.0.1:{self.port}/"
                f"BALANCO_ENERGIA_SUBSISTEMA_{year}.{extension}"
            ),
            extension=extension,
            origin="teste",
        )

    def test_downloads_and_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as destination:
            folder = Path(destination)
            first = ons_download._download_resource(
                resource=self._resource(2024, "csv"),
                folder=folder,
                force=False,
                timeout=10,
                progress=None,
                index=0,
                total_files=1,
            )
            self.assertFalse(first.from_cache)
            self.assertTrue(first.path.exists())
            self.assertGreater(first.size_bytes, 0)

            second = ons_download._download_resource(
                resource=self._resource(2024, "csv"),
                folder=folder,
                force=False,
                timeout=10,
                progress=None,
                index=0,
                total_files=1,
            )
            self.assertTrue(second.from_cache)

    def test_missing_file_raises_download_error(self) -> None:
        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaises(ons_download.DownloadError):
                ons_download._download_resource(
                    resource=self._resource(1999, "parquet"),
                    folder=Path(destination),
                    force=False,
                    timeout=10,
                    progress=None,
                    index=0,
                    total_files=1,
                )

    def test_report_falls_back_between_formats(self) -> None:
        with tempfile.TemporaryDirectory() as destination:
            targets = {
                2024: [
                    self._resource(2024, "parquet"),
                    self._resource(2024, "csv"),
                ]
            }
            original = ons_download.build_targets
            ons_download.build_targets = lambda *args, **kwargs: targets
            original_fetch = ons_download.fetch_resources
            ons_download.fetch_resources = lambda timeout=30: []
            try:
                report = ons_download.download_years(
                    years=[2024],
                    destination=Path(destination),
                )
            finally:
                ons_download.build_targets = original
                ons_download.fetch_resources = original_fetch

            self.assertFalse(report.errors)
            self.assertEqual(report.years, [2024])
            self.assertEqual(report.files[0].extension, "csv")


def _handler_for(root: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, *args) -> None:  # silencia o servidor de teste
            return

    return Handler


if __name__ == "__main__":
    unittest.main()
