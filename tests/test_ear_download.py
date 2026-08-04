from __future__ import annotations

from pathlib import Path

import requests

import ear_download as ed


class FakeResponse:
    def __init__(self, *, text: str = "", content: bytes = b"", status: int = 200):
        self.text = text
        self._content = content
        self.status_code = status
        self.headers = {"Content-Length": str(len(content))} if content else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def close(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._content


class FakeSession:
    def __init__(self, page: str, files: dict[str, bytes] | None = None):
        self.page = page
        self.files = files or {}

    def get(self, url: str, **kwargs):
        del kwargs
        if url == ed.DATASET_URL:
            return FakeResponse(text=self.page)
        return FakeResponse(content=self.files[url])

    def close(self) -> None:
        pass


def test_discover_parquet_resources() -> None:
    url = (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/"
        "ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_2026.parquet"
    )
    page = f'<a href="{url}">Parquet</a><a href="https://example.com/x.parquet">x</a>'
    resources = ed.discover_parquet_resources(FakeSession(page))
    assert resources == {2026: url}


def test_download_parquet_years(tmp_path: Path) -> None:
    url = (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/"
        "ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_2026.parquet"
    )
    page = f'<a href="{url}">Parquet</a>'
    parquet_bytes = b"PAR1" + b"test" + b"PAR1"
    batch = ed.download_parquet_years(
        [2026],
        tmp_path,
        session=FakeSession(page, {url: parquet_bytes}),
    )
    assert not batch.errors
    assert batch.total_bytes == len(parquet_bytes)
    assert batch.files[0][1].read_bytes() == parquet_bytes


def test_rejects_non_official_url() -> None:
    assert not ed._is_allowed_resource_url(
        "https://example.com/EAR_DIARIO_SUBSISTEMA_2026.parquet"
    )
