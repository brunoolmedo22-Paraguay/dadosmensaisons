from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import unquote, urljoin, urlsplit

import requests


DATASET_URL = "https://dados.ons.org.br/dataset/ear-diario-por-subsistema"
REQUEST_TIMEOUT = (15, 120)
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
MAX_PARQUET_SIZE = 25 * 1024 * 1024
USER_AGENT = (
    "EAR-Diario-ONS/1.0 "
    "(consulta automatizada ao Portal de Dados Abertos do ONS)"
)
ALLOWED_RESOURCE_HOSTS = {
    "dados.ons.org.br",
    "ons-aws-prod-opendata.s3.amazonaws.com",
    "ons-dl-prod-opendata.s3.amazonaws.com",
}
PARQUET_FILENAME_PATTERN = re.compile(
    r"^EAR_DIARIO_SUBSISTEMA_((?:19|20)\d{2})\.parquet$",
    flags=re.IGNORECASE,
)

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


def discover_parquet_resources(
    session: requests.Session | None = None,
) -> dict[int, str]:
    """Raspa o catálogo do ONS e retorna o link Parquet de cada ano."""
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

        resources: dict[int, str] = {}
        for href in parser.links:
            absolute_url = urljoin(DATASET_URL, href)
            parsed = urlsplit(absolute_url)
            filename = Path(unquote(parsed.path)).name
            match = PARQUET_FILENAME_PATTERN.fullmatch(filename)
            if not match or not _is_allowed_resource_url(absolute_url):
                continue
            resources[int(match.group(1))] = absolute_url

        if not resources:
            raise ONSDownloadError(
                "A página do ONS foi acessada, mas nenhum recurso Parquet anual "
                "de EAR foi encontrado. O portal pode ter alterado sua estrutura."
            )
        return dict(sorted(resources.items()))
    finally:
        if own_session:
            http.close()


def download_parquet_years(
    years: Iterable[int],
    destination: Path,
    progress_callback: ProgressCallback | None = None,
    session: requests.Session | None = None,
) -> DownloadBatch:
    """Descobre e baixa os arquivos anuais para uma pasta temporária."""
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
        resources = discover_parquet_resources(http)
        total = len(requested_years)

        for position, year in enumerate(requested_years, start=1):
            url = resources.get(year)
            if url is None:
                errors.append(
                    f"{year}: o portal do ONS não publicou um arquivo Parquet "
                    "de EAR para este ano."
                )
            else:
                filename = f"EAR_DIARIO_SUBSISTEMA_{year}.parquet"
                target = destination / filename
                try:
                    size = _download_one(http, url, target)
                    files.append((filename, target))
                    total_bytes += size
                except ONSDownloadError as exc:
                    errors.append(f"{year}: {exc}")

            if progress_callback is not None:
                progress_callback(position, total, year)
    finally:
        if own_session:
            http.close()

    return DownloadBatch(files=files, errors=errors, total_bytes=total_bytes)


def _download_one(
    session: requests.Session,
    url: str,
    target: Path,
) -> int:
    if not _is_allowed_resource_url(url):
        raise ONSDownloadError("o endereço encontrado não pertence à fonte oficial.")

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
                if int(declared_size) > MAX_PARQUET_SIZE:
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
                if written > MAX_PARQUET_SIZE:
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
        with target.open("rb") as handle:
            first_magic = handle.read(4)
            handle.seek(-4, 2)
            last_magic = handle.read(4)
    except (OSError, ValueError) as exc:
        target.unlink(missing_ok=True)
        raise ONSDownloadError("o arquivo baixado está incompleto.") from exc

    if first_magic != b"PAR1" or last_magic != b"PAR1":
        target.unlink(missing_ok=True)
        raise ONSDownloadError(
            "o conteúdo recebido não é um arquivo Parquet válido."
        )
    return written


def _is_allowed_resource_url(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    filename = Path(unquote(parsed.path)).name
    return (
        parsed.scheme == "https"
        and hostname in ALLOWED_RESOURCE_HOSTS
        and PARQUET_FILENAME_PATTERN.fullmatch(filename) is not None
    )


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/octet-stream;q=0.9,*/*;q=0.8",
        }
    )
    return session
