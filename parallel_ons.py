from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Iterable, Sequence


ProgressCallback = Callable[[int, int, int], None]
Downloader = Callable[..., Any]
Processor = Callable[[Any], Any]
EventCallback = Callable[["ProgressEvent"], None]


@dataclass(frozen=True)
class SourceSpec:
    """Configuração de uma base independente do ONS."""

    key: str
    label: str
    downloader: Downloader
    processor: Processor
    folder_name: str


@dataclass(frozen=True)
class ProgressEvent:
    """Evento emitido pelos workers e consumido na thread principal."""

    phase: str
    source_key: str
    source_label: str
    completed: int = 0
    total: int = 0
    year: int | None = None


@dataclass
class SourceOutcome:
    """Resultado isolado de uma base processada em paralelo."""

    source_key: str
    source_label: str
    result: Any | None = None
    total_bytes: int = 0
    error: Exception | None = None


def run_parallel_sources(
    specs: Sequence[SourceSpec],
    years: Iterable[int],
    temporary_root: Path,
    event_callback: EventCallback | None = None,
    max_workers: int = 3,
) -> list[SourceOutcome]:
    """Baixa e processa bases independentes em paralelo.

    Cada base usa seu próprio downloader, sua própria sessão HTTP e sua própria
    pasta temporária. Os callbacks dos downloaders apenas enfileiram eventos;
    ``event_callback`` é sempre executado na thread chamadora, permitindo que a
    interface do Streamlit seja atualizada com segurança.
    """
    source_specs = list(specs)
    requested_years = tuple(sorted({int(year) for year in years}))
    if not source_specs:
        return []
    if not requested_years:
        raise ValueError("Informe ao menos um ano para processamento.")

    root = Path(temporary_root)
    root.mkdir(parents=True, exist_ok=True)
    event_queue: Queue[ProgressEvent] = Queue()

    def emit_events() -> None:
        if event_callback is None:
            while True:
                try:
                    event_queue.get_nowait()
                except Empty:
                    return
        while True:
            try:
                event = event_queue.get_nowait()
            except Empty:
                return
            event_callback(event)

    def execute_source(spec: SourceSpec) -> SourceOutcome:
        def report_progress(completed: int, total: int, year: int) -> None:
            event_queue.put(
                ProgressEvent(
                    phase="download",
                    source_key=spec.key,
                    source_label=spec.label,
                    completed=completed,
                    total=total,
                    year=year,
                )
            )

        try:
            batch = spec.downloader(
                years=requested_years,
                destination=root / spec.folder_name,
                progress_callback=report_progress,
            )
            event_queue.put(
                ProgressEvent(
                    phase="validate",
                    source_key=spec.key,
                    source_label=spec.label,
                    completed=len(requested_years),
                    total=len(requested_years),
                )
            )
            result = spec.processor(batch.files)
            result.errors = [*batch.errors, *result.errors]
            return SourceOutcome(
                source_key=spec.key,
                source_label=spec.label,
                result=result,
                total_bytes=batch.total_bytes,
            )
        except Exception as exc:  # A falha de uma base não cancela as demais.
            return SourceOutcome(
                source_key=spec.key,
                source_label=spec.label,
                error=exc,
            )

    workers = max(1, min(int(max_workers), len(source_specs)))
    outcomes: list[SourceOutcome] = []
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="ons-source",
    ) as executor:
        futures: dict[Future[SourceOutcome], int] = {
            executor.submit(execute_source, spec): index
            for index, spec in enumerate(source_specs)
        }
        pending = set(futures)
        ordered: dict[int, SourceOutcome] = {}

        while pending:
            done, pending = wait(
                pending,
                timeout=0.10,
                return_when=FIRST_COMPLETED,
            )
            emit_events()
            for future in done:
                ordered[futures[future]] = future.result()

        emit_events()
        outcomes = [ordered[index] for index in sorted(ordered)]

    return outcomes
