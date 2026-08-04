from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ons_download import (
    DATASET_URL,
    ONSDownloadError,
    discover_parquet_resources,
    download_parquet_years,
)


OFFICIAL_BASE = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/balanco_energia_subsistema_ho"
)


class FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        body: bytes = b"",
        status_code: int = 200,
    ) -> None:
        self.text = text
        self.body = body
        self.status_code = status_code
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [
            self.body[index : index + chunk_size]
            for index in range(0, len(self.body), chunk_size)
        ]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses

    def get(
        self,
        url: str,
        *,
        stream: bool = False,
        timeout: tuple[int, int],
    ) -> FakeResponse:
        return self.responses[url]

    def close(self) -> None:
        pass


def resource_url(year: int) -> str:
    return f"{OFFICIAL_BASE}/BALANCO_ENERGIA_SUBSISTEMA_{year}.parquet"


def catalog_html(*years: int) -> str:
    links = "".join(
        f'<a href="{resource_url(year)}">Parquet {year}</a>'
        for year in years
    )
    return f"<html><body>{links}</body></html>"


class DiscoveryTests(unittest.TestCase):
    def test_scrapes_only_official_annual_parquet_links(self) -> None:
        valid_url = resource_url(2026)
        html = (
            "<html><body>"
            f'<a href="{valid_url}">Parquet oficial</a>'
            '<a href="https://example.com/BALANCO_ENERGIA_SUBSISTEMA_2025.parquet">'
            "Fora do ONS</a>"
            '<a href="https://ons-aws-prod-opendata.s3.amazonaws.com/arquivo.csv">'
            "CSV</a>"
            "</body></html>"
        )
        session = FakeSession({DATASET_URL: FakeResponse(text=html)})

        resources = discover_parquet_resources(session)

        self.assertEqual(resources, {2026: valid_url})

    def test_reports_changed_catalog_structure(self) -> None:
        session = FakeSession(
            {DATASET_URL: FakeResponse(text="<html>Sem links</html>")}
        )

        with self.assertRaises(ONSDownloadError):
            discover_parquet_resources(session)


class DownloadTests(unittest.TestCase):
    def test_downloads_requested_years_and_reports_missing_year(self) -> None:
        parquet_bytes = b"PAR1conteudo-de-testePAR1"
        url_2025 = resource_url(2025)
        url_2026 = resource_url(2026)
        session = FakeSession(
            {
                DATASET_URL: FakeResponse(text=catalog_html(2025, 2026)),
                url_2025: FakeResponse(body=parquet_bytes),
                url_2026: FakeResponse(body=parquet_bytes),
            }
        )
        progress: list[tuple[int, int, int]] = []

        with TemporaryDirectory() as temporary_directory:
            batch = download_parquet_years(
                years=[2024, 2025, 2026],
                destination=Path(temporary_directory),
                progress_callback=lambda done, total, year: progress.append(
                    (done, total, year)
                ),
                session=session,
            )
            downloaded_paths = [path for _, path in batch.files]
            self.assertTrue(all(path.exists() for path in downloaded_paths))

        self.assertEqual(len(batch.files), 2)
        self.assertEqual(batch.total_bytes, len(parquet_bytes) * 2)
        self.assertEqual(len(batch.errors), 1)
        self.assertIn("2024", batch.errors[0])
        self.assertEqual(progress[-1], (3, 3, 2026))

    def test_rejects_content_that_is_not_parquet(self) -> None:
        url_2026 = resource_url(2026)
        session = FakeSession(
            {
                DATASET_URL: FakeResponse(text=catalog_html(2026)),
                url_2026: FakeResponse(body=b"<html>erro</html>"),
            }
        )

        with TemporaryDirectory() as temporary_directory:
            batch = download_parquet_years(
                years=[2026],
                destination=Path(temporary_directory),
                session=session,
            )
            remaining_files = list(Path(temporary_directory).iterdir())

        self.assertFalse(batch.files)
        self.assertEqual(len(batch.errors), 1)
        self.assertIn("não é um arquivo Parquet válido", batch.errors[0])
        self.assertFalse(remaining_files)


if __name__ == "__main__":
    unittest.main()
