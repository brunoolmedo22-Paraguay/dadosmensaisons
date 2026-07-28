"""Descarga automática do conjunto Balanço de Energia nos Subsistemas do ONS.

O portal de dados abertos do ONS roda em CKAN. A lista oficial de arquivos é
obtida em `/api/3/action/package_show`. Caso a API esteja indisponível, o
módulo recorre ao padrão público de URL dos arquivos no S3 do ONS.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Sequence

import requests


DATASET_ID = "balanco-energia-subsistema"
PORTAL_URL = f"https://dados.ons.org.br/dataset/{DATASET_ID}"
CKAN_API_URL = "https://dados.ons.org.br/api/3/action/package_show"
S3_TEMPLATE = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/"
    "balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{year}.{extension}"
)

SUPPORTED_EXTENSIONS = ("parquet", "csv", "xlsx")
DEFAULT_FORMATS = ("parquet", "csv")
FIRST_YEAR = 2000
CACHE_DIR_NAME = "ons_balanco_energia_subsistema"
CHUNK_SIZE = 1 << 20
HEADERS = {"User-Agent": "balanco-mensal-sin/1.0 (Streamlit; dados abertos ONS)"}
YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


class DownloadError(RuntimeError):
    """Falha legível durante o acesso ao portal de dados abertos."""


@dataclass(frozen=True)
class RemoteResource:
    year: int
    url: str
    extension: str
    origin: str

    @property
    def filename(self) -> str:
        return f"BALANCO_ENERGIA_SUBSISTEMA_{self.year}.{self.extension}"


@dataclass
class DownloadedFile:
    year: int
    path: Path
    url: str
    extension: str
    size_bytes: int
    from_cache: bool

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class DownloadProgress:
    year: int
    index: int
    total_files: int
    downloaded_bytes: int
    total_bytes: int
    message: str

    @property
    def fraction(self) -> float:
        if self.total_files <= 0:
            return 0.0
        inner = 0.0
        if self.total_bytes > 0:
            inner = min(1.0, self.downloaded_bytes / self.total_bytes)
        return min(1.0, (self.index + inner) / self.total_files)


@dataclass
class DownloadReport:
    files: list[DownloadedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def years(self) -> list[int]:
        return sorted(item.year for item in self.files)


ProgressCallback = Callable[[DownloadProgress], None]


def cache_dir() -> Path:
    """Pasta temporária onde os arquivos baixados ficam guardados."""
    path = Path(tempfile.gettempdir()) / CACHE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_cache() -> int:
    """Apaga os arquivos já baixados e devolve quantos foram removidos."""
    path = Path(tempfile.gettempdir()) / CACHE_DIR_NAME
    if not path.exists():
        return 0
    removed = sum(1 for item in path.iterdir() if item.is_file())
    shutil.rmtree(path, ignore_errors=True)
    return removed


def cached_files() -> list[Path]:
    path = Path(tempfile.gettempdir()) / CACHE_DIR_NAME
    if not path.exists():
        return []
    return sorted(item for item in path.iterdir() if item.is_file())


def year_from_text(text: str) -> int | None:
    """Devolve o ano de quatro dígitos do texto quando ele for único."""
    years = {int(match) for match in YEAR_PATTERN.findall(str(text))}
    if len(years) != 1:
        return None
    return years.pop()


def fetch_resources(timeout: float = 30.0) -> list[RemoteResource]:
    """Consulta a API CKAN do ONS e devolve os arquivos anuais publicados."""
    try:
        response = requests.get(
            CKAN_API_URL,
            params={"id": DATASET_ID},
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise DownloadError(f"não foi possível consultar o portal do ONS ({exc})") from exc
    except ValueError as exc:
        raise DownloadError("o portal do ONS respondeu em formato inesperado") from exc

    if not payload.get("success"):
        raise DownloadError("o portal do ONS recusou a consulta ao conjunto de dados")

    raw_resources = payload.get("result", {}).get("resources", [])
    resources: list[RemoteResource] = []
    for item in raw_resources:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        extension = _extension_from(url, item.get("format"))
        if extension not in SUPPORTED_EXTENSIONS:
            continue
        year = year_from_text(Path(url).stem) or year_from_text(item.get("name") or "")
        if year is None:
            continue
        resources.append(
            RemoteResource(year=year, url=url, extension=extension, origin="portal")
        )
    if not resources:
        raise DownloadError("o portal não listou arquivos anuais reconhecíveis")
    return resources


def available_years(timeout: float = 30.0) -> tuple[list[int], str | None]:
    """Anos publicados no portal, com aviso quando é usada a lista padrão."""
    try:
        resources = fetch_resources(timeout=timeout)
    except DownloadError as exc:
        fallback = list(range(FIRST_YEAR, date.today().year + 1))
        return fallback, str(exc)
    years = sorted({resource.year for resource in resources})
    return years, None


def build_targets(
    years: Sequence[int],
    resources: Iterable[RemoteResource] | None = None,
    preferred_formats: Sequence[str] = DEFAULT_FORMATS,
) -> dict[int, list[RemoteResource]]:
    """Monta, para cada ano, a lista ordenada de endereços a tentar."""
    by_year: dict[int, list[RemoteResource]] = {year: [] for year in years}
    order = {name: position for position, name in enumerate(preferred_formats)}

    for resource in resources or []:
        if resource.year in by_year and resource.extension in order:
            by_year[resource.year].append(resource)

    for year in years:
        by_year[year].sort(key=lambda item: order.get(item.extension, 99))
        known = {item.url for item in by_year[year]}
        for extension in preferred_formats:
            url = S3_TEMPLATE.format(year=year, extension=extension)
            if url not in known:
                by_year[year].append(
                    RemoteResource(
                        year=year,
                        url=url,
                        extension=extension,
                        origin="padrão",
                    )
                )
    return by_year


def download_years(
    years: Sequence[int],
    preferred_formats: Sequence[str] = DEFAULT_FORMATS,
    destination: Path | None = None,
    force: bool = False,
    timeout: float = 60.0,
    progress: ProgressCallback | None = None,
) -> DownloadReport:
    """Baixa os arquivos anuais do ONS para uma pasta temporária."""
    report = DownloadReport()
    wanted = sorted({int(year) for year in years})
    if not wanted:
        report.errors.append("Nenhum ano foi selecionado.")
        return report

    folder = Path(destination) if destination else cache_dir()
    folder.mkdir(parents=True, exist_ok=True)

    try:
        resources = fetch_resources(timeout=timeout)
    except DownloadError as exc:
        resources = []
        report.warnings.append(
            f"Lista oficial indisponível ({exc}). Foi usado o padrão público de "
            "endereços do ONS."
        )

    published = {resource.year for resource in resources}
    if published:
        unknown = [year for year in wanted if year not in published]
        if unknown:
            report.warnings.append(
                "O portal não lista arquivo para: "
                f"{', '.join(map(str, unknown))}. A tentativa será feita mesmo assim."
            )

    targets = build_targets(wanted, resources, preferred_formats)

    for index, year in enumerate(wanted):
        candidates = targets[year]
        last_error: str | None = None
        for candidate in candidates:
            try:
                downloaded = _download_resource(
                    resource=candidate,
                    folder=folder,
                    force=force,
                    timeout=timeout,
                    progress=progress,
                    index=index,
                    total_files=len(wanted),
                )
            except DownloadError as exc:
                last_error = str(exc)
                continue
            report.files.append(downloaded)
            last_error = None
            break
        if last_error is not None:
            report.errors.append(f"{year}: {last_error}")

    return report


def _download_resource(
    resource: RemoteResource,
    folder: Path,
    force: bool,
    timeout: float,
    progress: ProgressCallback | None,
    index: int,
    total_files: int,
) -> DownloadedFile:
    target = folder / resource.filename

    if target.exists() and target.stat().st_size > 0 and not force:
        _notify(
            progress,
            year=resource.year,
            index=index,
            total_files=total_files,
            downloaded=1,
            total=1,
            message=f"{resource.year} já estava na pasta temporária",
        )
        return DownloadedFile(
            year=resource.year,
            path=target,
            url=resource.url,
            extension=resource.extension,
            size_bytes=target.stat().st_size,
            from_cache=True,
        )

    partial = target.with_suffix(target.suffix + ".part")
    attempts = 3
    last_exception: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with requests.get(
                resource.url,
                headers=HEADERS,
                timeout=timeout,
                stream=True,
            ) as response:
                if response.status_code == 404:
                    raise DownloadError(
                        f"arquivo {resource.extension} não publicado para {resource.year}"
                    )
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        _notify(
                            progress,
                            year=resource.year,
                            index=index,
                            total_files=total_files,
                            downloaded=downloaded,
                            total=total,
                            message=(
                                f"Baixando {resource.year} "
                                f"({_human_size(downloaded)}"
                                + (f" de {_human_size(total)}" if total else "")
                                + ")"
                            ),
                        )
            if downloaded == 0:
                raise DownloadError("o servidor devolveu um arquivo vazio")
            partial.replace(target)
            return DownloadedFile(
                year=resource.year,
                path=target,
                url=resource.url,
                extension=resource.extension,
                size_bytes=target.stat().st_size,
                from_cache=False,
            )
        except DownloadError:
            partial.unlink(missing_ok=True)
            raise
        except requests.RequestException as exc:
            last_exception = exc
            partial.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(1.5 * attempt)

    raise DownloadError(f"falha ao baixar ({last_exception})")


def _notify(
    progress: ProgressCallback | None,
    year: int,
    index: int,
    total_files: int,
    downloaded: int,
    total: int,
    message: str,
) -> None:
    if progress is None:
        return
    progress(
        DownloadProgress(
            year=year,
            index=index,
            total_files=total_files,
            downloaded_bytes=downloaded,
            total_bytes=total,
            message=message,
        )
    )


def _extension_from(url: str, declared_format: object) -> str:
    suffix = Path(url.split("?")[0]).suffix.lower().lstrip(".")
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix
    declared = str(declared_format or "").strip().lower()
    return declared if declared in SUPPORTED_EXTENSIONS else ""


def _human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
