from __future__ import annotations

from pathlib import Path

import ena_download as ed


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"", headers: dict[str, str] | None = None):
        self.text = text
        self._content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._content

    def close(self) -> None:
        return None


class FakeSession:
    def __init__(self, page: str, payloads: dict[str, bytes] | None = None):
        self.page = page
        self.payloads = payloads or {}

    def get(self, url: str, **kwargs):
        del kwargs
        if url == ed.DATASET_URL:
            return FakeResponse(text=self.page)
        payload = self.payloads[url]
        return FakeResponse(content=payload, headers={"Content-Length": str(len(payload))})

    def close(self) -> None:
        return None


def test_discover_parquet_resources() -> None:
    url = (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/"
        "ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_2026.parquet"
    )
    page = f'<a href="{url}">Parquet</a><a href="https://example.com/fake.parquet">x</a>'
    resources = ed.discover_parquet_resources(FakeSession(page))
    assert resources == {2026: url}


def test_download_parquet_years(tmp_path: Path) -> None:
    url = (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/"
        "ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_2026.parquet"
    )
    page = f'<a href="{url}">Parquet</a>'
    parquet = b"PAR1" + b"sample" + b"PAR1"
    batch = ed.download_parquet_years(
        years=[2026],
        destination=tmp_path,
        session=FakeSession(page, {url: parquet}),
    )
    assert not batch.errors
    assert batch.total_bytes == len(parquet)
    assert batch.files[0][0] == "ENA_DIARIO_SUBSISTEMA_2026.parquet"
    assert batch.files[0][1].read_bytes() == parquet


def test_rejects_non_official_url() -> None:
    assert not ed._is_allowed_resource_url(
        "https://example.com/ENA_DIARIO_SUBSISTEMA_2026.parquet"
    )
