"""E2E real: baixa e concatena 2025+2026 ONS via DuckDB sem Pandas multi-ano."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import resource
import time

import duckdb

from termicas_download import download_thermal_years
from termicas_processing import process_thermal_files, release_thermal_cache
from termicas_duckdb import query_thermal, export_thermal


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    start = time.monotonic()
    with TemporaryDirectory(prefix="ons_thermal_e2e_") as root:
        downloaded = download_thermal_years(
            [2025, 2026], Path(root),
            progress_callback=lambda i, n, y: print(
                f"DOWNLOAD YEAR {y}: {i}/{n}", flush=True
            ),
        )
        print(f"FILES={len(downloaded.files)} BYTES={downloaded.total_bytes} "
              f"ERRORS={downloaded.errors} PEAK_MB={peak_mb():.1f}", flush=True)
        assert not downloaded.errors, downloaded.errors
        assert len(downloaded.files) >= 23
        assert all(name.lower().endswith(".parquet") for name, _ in downloaded.files)
        result = process_thermal_files(downloaded.files)
        try:
            assert not result.errors, result.errors
            print(f"INVENTORY={result.total_rows} MONTHS={len(result.file_paths)} "
                  f"BOUNDS={result.bounds} PEAK_MB={peak_mb():.1f}", flush=True)
            assert len(result.file_paths) >= 23
            monthly, ranking, rows, plants, hours, preview, payload = query_thermal(
                result, date(2025, 1, 1), date(2026, 11, 30), {},
                "monthly", ["val_proggeracao", "val_verifgeracao"],
            )
            print(f"QUERY MONTHS={len(monthly)} ROWS={rows} PLANTS={plants} "
                  f"HOURS={hours} PEAK_MB={peak_mb():.1f} "
                  f"TIME_S={time.monotonic()-start:.1f}", flush=True)
            assert len(monthly) >= 23
            assert rows == result.total_rows
            assert rows > 1_000_000
            assert monthly["val_verifgeracao"].notna().any()
            file = export_thermal(result, "parquet")
            con = duckdb.connect()
            try:
                actual_rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(file)]).fetchone()[0]
                columns = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(file)]).fetchall()
            finally:
                con.close()
            print(f"EXPORT ROWS={actual_rows} COLUMNS={len(columns)} "
                  f"PARQUET_MB={file.stat().st_size/1e6:.2f} "
                  f"PEAK_MB={peak_mb():.1f}", flush=True)
            assert actual_rows == result.total_rows
            assert len(columns) >= 45
        finally:
            release_thermal_cache(result)
    print(f"LIVE_E2E_2025_2026=PASS elapsed={time.monotonic()-start:.1f}s "
          f"PEAK_MB={peak_mb():.1f}", flush=True)


if __name__ == "__main__":
    main()
