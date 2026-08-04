from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Literal
from urllib.parse import unquote, urljoin, urlsplit

import requests


DATASET_URL = "https://dados.ons.org.br/dataset/ena-diario-por-subsistema"
REQUEST_TIMEOUT = (15, 120)
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
MAX_RESOURCE_SIZE = 25 * 1024 * 1024
USER_AGENT = (
    "ENA-Diario-ONS/1.1 "
    "(consulta automatizada ao Portal de Dados Abertos do ONS)"
)
ALLOWED_RESOURCE_HOSTS = {
    "dados.ons.org.br",
    "ons-aws-prod-opendata.s3.amazonaws.com",
    "ons-dl-prod-opendata.s3.amazonaws.com",
}
RESOURCE_FILENAME_PATTERN = re.compile(
    r"^ENA_DIARIO_SUBSISTEMA_((?:19|20)\d{2})\.(parquet|csv)$",
    flags=re.IGNORECASE,
)

ResourceFormat = Literal["parquet", "csv"]
ProgressCallback = Callable[[int, int, int], None]


class ONSDownloadError(RuntimeError):
    """Erro legível ao consultar ou baixar dados públicos do ONS."""


@dataclass
class DownloadBatch:
    files: list[tuple[str, Path]]
    errors: list[str]
    total_bytes: int


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def discover_resources(
    session: requests.Session | None = None,
) -> dict[int, dict[ResourceFormat, str]]:
    """Raspa o catálogo e retorna os recursos CSV/Parquet disponíveis por ano."""
    own_session = session is None
    http = session or _new_session()
    try:
        response: requests.Response | None = None
        try:
            response = http.get(DATASET_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            if response is not None:
                response.close()
            raise ONSDownloadError(
                "Não foi possível consultar a página de dados do ONS. "
                "Verifique a conexão com a internet e tente novamente."
            ) from exc

        try:
            parser = _LinkCollector()
            parser.feed(response.text)
        finally:
            response.close()

        resources: dict[int, dict[ResourceFormat, str]] = {}
        for href in parser.links:
            absolute_url = urljoin(DATASET_URL, href)
            parsed = urlsplit(absolute_url)
            filename = Path(unquote(parsed.path)).name
            match = RESOURCE_FILENAME_PATTERN.fullmatch(filename)
            if not match or not _is_allowed_resource_url(absolute_url):
                continue
            year = int(match.group(1))
            resource_format = match.group(2).lower()
            resources.setdefault(year, {})[resource_format] = absolute_url  # type: ignore[index]

        if not resources:
            raise ONSDownloadError(
                "A página do ONS foi acessada, mas nenhum recurso anual CSV ou "
                "Parquet de ENA foi encontrado. O portal pode ter alterado sua estrutura."
            )
        return dict(sorted(resources.items()))
    finally:
        if own_session:
            http.close()


def discover_parquet_resources(
    session: requests.Session | None = None,
) -> dict[int, str]:
    """Compatibilidade: retorna somente os links Parquet descobertos."""
    resources = discover_resources(session)
    return {
        year: formats["parquet"]
        for year, formats in resources.items()
        if "parquet" in formats
    }


def download_ena_years(
    years: Iterable[int],
    destination: Path,
    progress_callback: ProgressCallback | None = None,
    session: requests.Session | None = None,
) -> DownloadBatch:
    """Baixa ENA anual, priorizando Parquet e usando CSV como fallback."""
    requested_years = sorted({int(year) for year in years})
    if not requested_years:
        raise ValueError("Informe ao menos um ano para download.")

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    own_session = session is None
    http = session or _new_session()
    files: list[tuple[str, Path]] = []
    errors: list[str] = []
    total_bytes = 0

    try:
        resources = discover_resources(http)
        total = len(requested_years)

        for position, year in enumerate(requested_years, start=1):
            year_resources = resources.get(year, {})
            candidates: list[tuple[ResourceFormat, str]] = []
            if "parquet" in year_resources:
                candidates.append(("parquet", year_resources["parquet"]))
            if "csv" in year_resources:
                candidates.append(("csv", year_resources["csv"]))

            if not candidates:
                errors.append(
                    f"{year}: o portal do ONS não publicou arquivo Parquet nem CSV "
                    "de ENA para este ano."
                )
            else:
                attempt_errors: list[str] = []
                for resource_format, url in candidates:
                    filename = f"ENA_DIARIO_SUBSISTEMA_{year}.{resource_format}"
                    target = destination / filename
                    try:
                        size = _download_one(http, url, target, resource_format)
                        files.append((filename, target))
                        total_bytes += size
                        break
                    except ONSDownloadError as exc:
                        attempt_errors.append(f"{resource_format.upper()}: {exc}")
                else:
                    errors.append(f"{year}: " + " | ".join(attempt_errors))

            if progress_callback is not None:
                progress_callback(position, total, year)
    finally:
        if own_session:
            http.close()

    return DownloadBatch(files=files, errors=errors, total_bytes=total_bytes)


# Mantém compatibilidade com versões anteriores do app e testes externos.
download_parquet_years = download_ena_years


def _download_one(
    session: requests.Session,
    url: str,
    target: Path,
    resource_format: ResourceFormat | None = None,
) -> int:
    if not _is_allowed_resource_url(url):
        raise ONSDownloadError("o endereço encontrado não pertence à fonte oficial.")

    detected_format = resource_format or _resource_format_from_url(url)
    response: requests.Response | None = None
    try:
        response = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        if response is not None:
            response.close()
        raise ONSDownloadError(
            "não foi possível baixar o arquivo publicado pelo ONS."
        ) from exc

    written = 0
    try:
        declared_size = response.headers.get("Content-Length")
        if declared_size:
            try:
                if int(declared_size) > MAX_RESOURCE_SIZE:
                    raise ONSDownloadError(
                        "o arquivo excede o limite de segurança de 25 MB."
                    )
            except ValueError:
                pass

        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_RESOURCE_SIZE:
                    raise ONSDownloadError(
                        "o arquivo excede o limite de segurança de 25 MB."
                    )
                handle.write(chunk)
    except ONSDownloadError:
        target.unlink(missing_ok=True)
        raise
    except requests.RequestException as exc:
        target.unlink(missing_ok=True)
        raise ONSDownloadError(
            "a conexão foi interrompida durante o download."
        ) from exc
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ONSDownloadError(
            "não foi possível gravar o arquivo na pasta temporária."
        ) from exc
    finally:
        if response is not None:
            response.close()

    try:
        if detected_format == "parquet":
            _validate_parquet(target)
        else:
            _validate_csv(target)
    except ONSDownloadError:
        target.unlink(missing_ok=True)
        raise
    return written


def _validate_parquet(target: Path) -> None:
    try:
        with target.open("rb") as handle:
            first_magic = handle.read(4)
            handle.seek(-4, 2)
            last_magic = handle.read(4)
    except (OSError, ValueError) as exc:
        raise ONSDownloadError("o arquivo baixado está incompleto.") from exc

    if first_magic != b"PAR1" or last_magic != b"PAR1":
        raise ONSDownloadError(
            "o conteúdo recebido não é um arquivo Parquet válido."
        )


def _validate_csv(target: Path) -> None:
    try:
        sample = target.read_bytes()[:16384]
    except OSError as exc:
        raise ONSDownloadError("o arquivo baixado está incompleto.") from exc
    if not sample or b"\x00" in sample:
        raise ONSDownloadError("o conteúdo recebido não é um CSV válido.")
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ONSDownloadError("o CSV recebido não está codificado em UTF-8.") from exc

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    normalized = first_line.lower().replace('"', "")
    if normalized.startswith("<html") or normalized.startswith("<!doctype"):
        raise ONSDownloadError("o endereço retornou uma página HTML em vez do CSV.")
    if "id_subsistema" not in normalized or "ena_data" not in normalized:
        raise ONSDownloadError(
            "o CSV recebido não possui o cabeçalho esperado da base de ENA."
        )
    if ";" not in first_line and "," not in first_line:
        raise ONSDownloadError("o CSV recebido não possui um delimitador reconhecível.")


def _resource_format_from_url(url: str) -> ResourceFormat:
    match = RESOURCE_FILENAME_PATTERN.fullmatch(
        Path(unquote(urlsplit(url).path)).name
    )
    if not match:
        raise ONSDownloadError("não foi possível identificar o formato do recurso.")
    return match.group(2).lower()  # type: ignore[return-value]


def _is_allowed_resource_url(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    filename = Path(unquote(parsed.path)).name
    return (
        parsed.scheme == "https"
        and hostname in ALLOWED_RESOURCE_HOSTS
        and RESOURCE_FILENAME_PATTERN.fullmatch(filename) is not None
    )


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/csv,application/octet-stream;q=0.9,*/*;q=0.8",
        }
    )
    return session
