"""Descoberta e download seguro dos arquivos térmicos do ONS."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import unquote, urljoin, urlsplit

import requests

DATASET_URL = "https://dados.ons.org.br/dataset/geracao-termica-despacho-2"
HOSTS = {"dados.ons.org.br", "ons-aws-prod-opendata.s3.amazonaws.com",
         "ons-dl-prod-opendata.s3.amazonaws.com"}
# 2013-2021: GERACAO_TERMICA_DESPACHO_2021.parquet
# 2022+: GERACAO_TERMICA_DESPACHO-2_2026_01.parquet
ANNUAL = re.compile(r"^GERACAO_TERMICA_DESPACHO[_-]((?:19|20)\d{2})\.(parquet|csv)$", re.I)
MONTHLY = re.compile(r"^GERACAO_TERMICA_DESPACHO[-_]2[_-]((?:19|20)\d{2})[_-](0[1-9]|1[0-2])\.(parquet|csv)$", re.I)
MAX_FILE_BYTES = 250 * 1024 * 1024
CHUNK = 1024 * 1024
TIMEOUT = (15, 120)
ProgressCallback = Callable[[int, int, int], None]


class ThermalDownloadError(RuntimeError):
    """Falha recuperável ao consultar dados abertos do ONS."""


@dataclass
class DownloadBatch:
    files: list[tuple[str, Path]]
    errors: list[str]
    total_bytes: int


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _resource(url: str) -> tuple[int, int | None, str] | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in HOSTS:
        return None
    filename = Path(unquote(parsed.path)).name
    matched = MONTHLY.fullmatch(filename)
    if matched:
        return int(matched[1]), int(matched[2]), matched[3].lower()
    matched = ANNUAL.fullmatch(filename)
    if matched:
        return int(matched[1]), None, matched[2].lower()
    return None


def discover_resources(session: requests.Session | None = None) -> dict[tuple[int, int | None], dict[str, str]]:
    own = session is None
    http = session or requests.Session()
    try:
        try:
            response = http.get(DATASET_URL, timeout=TIMEOUT)
            response.raise_for_status()
            parser = _Links()
            parser.feed(response.text)
            response.close()
        except requests.RequestException as exc:
            raise ThermalDownloadError("Falha ao consultar o catálogo do ONS.") from exc
        resources: dict[tuple[int, int | None], dict[str, str]] = {}
        for href in parser.hrefs:
            url = urljoin(DATASET_URL, href)
            key = _resource(url)
            if key is None:
                continue
            year, month, fmt = key
            resources.setdefault((year, month), {})[fmt] = url
        if not resources:
            raise ThermalDownloadError("Nenhum recurso térmico CSV/Parquet identificado no catálogo do ONS.")
        return resources
    finally:
        if own:
            http.close()


def _download_one(http: requests.Session, url: str, target: Path, fmt: str) -> int:
    info = _resource(url)
    if info is None or info[2] != fmt:
        raise ThermalDownloadError("URL ou formato não autorizado.")
    written = 0
    try:
        with http.get(url, stream=True, timeout=TIMEOUT) as response:
            response.raise_for_status()
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_FILE_BYTES:
                raise ThermalDownloadError("Arquivo maior que o limite de 250 MB.")
            with target.open("wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK):
                    if chunk:
                        written += len(chunk)
                        if written > MAX_FILE_BYTES:
                            raise ThermalDownloadError("Arquivo maior que o limite de 250 MB.")
                        file.write(chunk)
        if fmt == "parquet":
            with target.open("rb") as file:
                first = file.read(4)
                file.seek(-4, 2)
                last = file.read(4)
            if first != b"PAR1" or last != b"PAR1":
                raise ThermalDownloadError("O conteúdo não é Parquet válido.")
        else:
            with target.open("rb") as file:
                sample = file.read(16384)
            if not sample or b"\x00" in sample:
                raise ThermalDownloadError("CSV vazio ou inválido.")
            head = sample.decode("utf-8-sig")
            first = head.lower().lstrip()
            if first.startswith("<html") or first.startswith("<!doctype") or "din_instante" not in first:
                raise ThermalDownloadError("CSV não contém o cabeçalho oficial esperado.")
    except (requests.RequestException, OSError, UnicodeError, ValueError) as exc:
        target.unlink(missing_ok=True)
        raise ThermalDownloadError("Falha ao baixar ou validar o arquivo.") from exc
    except ThermalDownloadError:
        target.unlink(missing_ok=True)
        raise
    return written


def download_thermal_years(
    years: Iterable[int],
    destination: Path,
    progress_callback: ProgressCallback | None = None,
    session: requests.Session | None = None,
) -> DownloadBatch:
    years = sorted({int(year) for year in years})
    if not years:
        raise ValueError("Selecione ao menos um ano.")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    own = session is None
    http = session or requests.Session()
    http.headers.update({"User-Agent": "DadosMensaisONS-Termicas/1.0"})
    files: list[tuple[str, Path]] = []
    errors: list[str] = []
    total_bytes = 0
    try:
        catalog = discover_resources(http)
        for index, year in enumerate(years, start=1):
            monthly_keys = sorted(
                (y, m) for y, m in catalog if y == year and m is not None
            )
            # Preferir os arquivos mensais quando coexistem com anuais (2022/2023).
            keys = monthly_keys or ([(year, None)] if (year, None) in catalog else [])
            if not keys:
                errors.append(f"{year}: o ONS não disponibiliza arquivos para este período.")
            for key in keys:
                formats = catalog[key]
                failures: list[str] = []
                for fmt in ("parquet", "csv"):
                    url = formats.get(fmt)
                    if not url:
                        continue
                    name = Path(unquote(urlsplit(url).path)).name
                    target = destination / name
                    try:
                        size = _download_one(http, url, target, fmt)
                        files.append((name, target))
                        total_bytes += size
                        break
                    except ThermalDownloadError as exc:
                        failures.append(f"{fmt.upper()}: {exc}")
                else:
                    errors.append(f"{year}/{key[1] or 'anual'}: " + (" | ".join(failures) or "nenhum formato disponível"))
            if progress_callback is not None:
                progress_callback(index, len(years), year)
    finally:
        if own:
            http.close()
    return DownloadBatch(files=files, errors=errors, total_bytes=total_bytes)
