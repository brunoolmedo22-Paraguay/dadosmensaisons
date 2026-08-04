from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from parallel_ons import ProgressEvent, SourceSpec, run_parallel_sources


class ParallelPipelineTests(unittest.TestCase):
    def test_sources_start_concurrently_and_preserve_order(self) -> None:
        barrier = threading.Barrier(3, timeout=2)
        main_thread = threading.get_ident()
        event_threads: list[int] = []
        events: list[ProgressEvent] = []

        def make_downloader(source: str):
            def downloader(*, years, destination, progress_callback):
                Path(destination).mkdir(parents=True, exist_ok=True)
                barrier.wait()
                progress_callback(1, 1, int(tuple(years)[0]))
                return SimpleNamespace(
                    files=[(f"{source}.parquet", Path(destination) / f"{source}.parquet")],
                    errors=[],
                    total_bytes=10,
                )
            return downloader

        def processor(files):
            return SimpleNamespace(files=files, errors=[], warnings=[])

        specs = [
            SourceSpec(key=key, label=key, downloader=make_downloader(key), processor=processor, folder_name=key.lower())
            for key in ("BALANCO", "EAR", "ENA")
        ]

        def on_event(event: ProgressEvent) -> None:
            event_threads.append(threading.get_ident())
            events.append(event)

        with TemporaryDirectory() as temporary_directory:
            outcomes = run_parallel_sources(
                specs=specs,
                years=[2026],
                temporary_root=Path(temporary_directory),
                event_callback=on_event,
                max_workers=3,
            )

        self.assertEqual([item.source_key for item in outcomes], ["BALANCO", "EAR", "ENA"])
        self.assertTrue(all(item.error is None for item in outcomes))
        self.assertEqual(sum(item.total_bytes for item in outcomes), 30)
        self.assertTrue(events)
        self.assertTrue(all(thread_id == main_thread for thread_id in event_threads))

    def test_failure_in_one_source_does_not_cancel_others(self) -> None:
        def good_downloader(*, years, destination, progress_callback):
            progress_callback(1, 1, int(tuple(years)[0]))
            return SimpleNamespace(files=[], errors=[], total_bytes=1)

        def bad_downloader(*, years, destination, progress_callback):
            raise RuntimeError("falha simulada")

        def processor(files):
            return SimpleNamespace(errors=[], warnings=[])

        specs = [
            SourceSpec("BALANCO", "Balanço", good_downloader, processor, "balanco"),
            SourceSpec("EAR", "EAR", bad_downloader, processor, "ear"),
            SourceSpec("ENA", "ENA", good_downloader, processor, "ena"),
        ]

        with TemporaryDirectory() as temporary_directory:
            outcomes = run_parallel_sources(
                specs,
                [2026],
                Path(temporary_directory),
                max_workers=3,
            )

        by_key = {item.source_key: item for item in outcomes}
        self.assertIsNone(by_key["BALANCO"].error)
        self.assertIsInstance(by_key["EAR"].error, RuntimeError)
        self.assertIsNone(by_key["ENA"].error)


if __name__ == "__main__":
    unittest.main()
