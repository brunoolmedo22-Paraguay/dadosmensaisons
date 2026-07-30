from __future__ import annotations

from pathlib import Path

import ena_download as ed


CSV_BYTES = (
    "id_subsistema;nom_subsistema;ena_data;"
    "ena_bruta_regiao_mwmed;ena_bruta_regiao_percentualmlt;"
    "ena_armazenavel_regiao_mwmed;ena_armazenavel_regiao_percentualmlt\n"
    "SE;Sudeste/Centro-Oeste;01/01/2020;100,0;50,0;80,0;40,0\n"
).encode("utf-8")


class FakeResponse:
    def __init__(
        self,
        text: str = "",
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
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
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs):
        del kwargs
        self.requested_urls.append(url)
        if url == ed.DATASET_URL:
            return FakeResponse(text=self.page)
        payload = self.payloads[url]
        return FakeResponse(content=payload, headers={"Content-Length": str(len(payload))})

    def close(self) -> None:
        return None


def official_url(year: int, suffix: str) -> str:
    return (
        "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/"
        f"ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{year}.{suffix}"
    )


def test_discovers_csv_and_parquet_resources() -> None:
    parquet_url = official_url(2021, "parquet")
    csv_url = official_url(2020, "csv")
    page = (
        f'<a href="{parquet_url}">Parquet</a>'
        f'<a href="{csv_url}">CSV</a>'
        '<a href="https://example.com/ENA_DIARIO_SUBSISTEMA_2019.csv">x</a>'
    )
    resources = ed.discover_resources(FakeSession(page))
    assert resources == {
        2020: {"csv": csv_url},
        2021: {"parquet": parquet_url},
    }
    assert ed.discover_parquet_resources(FakeSession(page)) == {2021: parquet_url}


def test_downloads_csv_when_parquet_does_not_exist(tmp_path: Path) -> None:
    csv_url = official_url(2020, "csv")
    page = f'<a href="{csv_url}">CSV</a>'
    batch = ed.download_ena_years(
        years=[2020],
        destination=tmp_path,
        session=FakeSession(page, {csv_url: CSV_BYTES}),
    )
    assert not batch.errors
    assert batch.total_bytes == len(CSV_BYTES)
    assert batch.files[0][0] == "ENA_DIARIO_SUBSISTEMA_2020.csv"
    assert batch.files[0][1].read_bytes() == CSV_BYTES


def test_prefers_parquet_when_both_formats_exist(tmp_path: Path) -> None:
    parquet_url = official_url(2021, "parquet")
    csv_url = official_url(2021, "csv")
    parquet = b"PAR1" + b"sample" + b"PAR1"
    page = f'<a href="{csv_url}">CSV</a><a href="{parquet_url}">Parquet</a>'
    session = FakeSession(page, {parquet_url: parquet, csv_url: CSV_BYTES})
    batch = ed.download_ena_years(
        years=[2021],
        destination=tmp_path,
        session=session,
    )
    assert not batch.errors
    assert batch.files[0][0].endswith(".parquet")
    assert csv_url not in session.requested_urls


def test_falls_back_to_csv_when_parquet_is_invalid(tmp_path: Path) -> None:
    parquet_url = official_url(2021, "parquet")
    csv_url = official_url(2021, "csv")
    page = f'<a href="{parquet_url}">Parquet</a><a href="{csv_url}">CSV</a>'
    session = FakeSession(page, {parquet_url: b"not parquet", csv_url: CSV_BYTES})
    batch = ed.download_ena_years(
        years=[2021],
        destination=tmp_path,
        session=session,
    )
    assert not batch.errors
    assert batch.files[0][0].endswith(".csv")
    assert not (tmp_path / "ENA_DIARIO_SUBSISTEMA_2021.parquet").exists()


def test_rejects_non_official_url_and_accepts_csv() -> None:
    assert not ed._is_allowed_resource_url(
        "https://example.com/ENA_DIARIO_SUBSISTEMA_2020.csv"
    )
    assert ed._is_allowed_resource_url(official_url(2020, "csv"))
