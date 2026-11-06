"""Mede Parquet real do ONS, para diferenciar tamanho, RAM e falhas de rede."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import os
import requests
import pandas as pd
from termicas_download import discover_resources, _download_one

catalog = discover_resources()
for year in (2025, 2026):
    keys = sorted(k for k in catalog if k[0] == year and k[1] is not None)
    print(f"CATALOG {year}: {len(keys)} months; parquet={sum('parquet' in catalog[k] for k in keys)}, csv={sum('csv' in catalog[k] for k in keys)}", flush=True)
    sizes = []
    for key in keys:
        url = catalog[key].get("parquet")
        if url:
            try:
                head = requests.head(url, timeout=(10, 30))
                head.raise_for_status()
                sizes.append(int(head.headers.get("Content-Length", "0")))
            except Exception as exc:
                print(f"HEAD FAILED {key}: {exc}", flush=True)
    print(f"PARQUET HEAD {year}: total MB={sum(sizes)/1e6:.3f}; sample sizes={[round(v/1024) for v in sizes]}", flush=True)

with TemporaryDirectory() as td:
    for year, month in ((2025, 1), (2026, 1)):
        url = catalog[(year, month)]["parquet"]
        output=Path(td)/Path(url).name
        started=monotonic()
        bytes_ = _download_one(requests.Session(), url, output, "parquet")
        read_started=monotonic()
        data = pd.read_parquet(output)
        print(f"PROFILE {year}-{month:02}: file KB={bytes_/1024:.1f}, rows={len(data)}, cols={len(data.columns)}, "
              f"mem MB={data.memory_usage(deep=True).sum()/1e6:.1f}, download s={read_started-started:.2f}, "
              f"read s={monotonic()-read_started:.2f}, fields={list(data.columns)}", flush=True)
        del data
