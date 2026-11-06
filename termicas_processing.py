"""Leitura, validação e agregação sem dupla contagem dos dados térmicos do ONS."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

Granularity = Literal["hourly", "daily", "monthly", "yearly"]
FREQUENCIES: dict[str, str] = {
    "hourly": "h", "daily": "D", "monthly": "MS", "yearly": "YS"
}

REQUIRED = {"din_instante", "nom_usina", "id_subsistema", "val_proggeracao", "val_verifgeracao"}
PRIMARY_METRICS = ("val_proggeracao", "val_verifgeracao", "val_geracaodespachada")
METRIC_LABELS = {
    "val_proggeracao": "Geração programada total (MWmed)",
    "val_verifgeracao": "Geração verificada total (MWmed)",
    "val_geracaodespachada": "Geração despachada (MWmed)",
    "val_progordemmerito": "Programada · ordem de mérito (MWmed)",
    "val_verifordemmerito": "Verificada · ordem de mérito (MWmed)",
    "val_proginflexibilidade": "Programada · inflexibilidade (MWmed)",
    "val_verifinflexibilidade": "Verificada · inflexibilidade (MWmed)",
    "val_prograzaoeletrica": "Programada · razão elétrica (MWmed)",
    "val_verifrazaoeletrica": "Verificada · razão elétrica (MWmed)",
    "val_proggarantiaenergetica": "Programada · segurança energética (MWmed)",
    "val_verifgarantiaenergetica": "Verificada · segurança energética (MWmed)",
    "val_progexportacao": "Programada · exportação (MWmed)",
    "val_verifexportacao": "Verificada · exportação (MWmed)",
    "val_progreservapotencia": "Programada · reserva operativa (MWmed)",
    "val_verifreservapotencia": "Verificada · reserva operativa (MWmed)",
    "val_progunitcommitment": "Programada · unit commitment (MWmed)",
    "val_verifunitcommitment": "Verificada · unit commitment (MWmed)",
    "val_progconstrainedoff": "Programada · constrained-off (MWmed)",
    "val_verifconstrainedoff": "Verificada · constrained-off (MWmed)",
    "val_progordemdemeritoref": "Referência de despacho por mérito (MWmed)",
    "val_proginflexpura": "Programada · inflexibilidade pura (MWmed)",
    "val_verifinflexpura": "Verificada · inflexibilidade pura (MWmed)",
}


@dataclass
class ThermalResult:
    hourly: pd.DataFrame
    metric_columns: list[str]
    file_report: pd.DataFrame
    errors: list[str]
    warnings: list[str]


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
    raise ValueError("Formato não suportado.")


def process_thermal_files(files: Iterable[tuple[str, Path]]) -> ThermalResult:
    frames: list[pd.DataFrame] = []
    report: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    for name, path in files:
        try:
            data = _read(Path(path))
            data.columns = [str(column).strip().lower() for column in data.columns]
            missing = REQUIRED.difference(data.columns)
            if missing:
                raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(sorted(missing)))
            data["din_instante"] = pd.to_datetime(data["din_instante"], errors="coerce")
            invalid = int(data["din_instante"].isna().sum())
            data = data.dropna(subset=["din_instante"]).copy()
            for column in data.columns:
                if column.startswith(("val_prog", "val_verif")) or column == "val_geracaodespachada":
                    if not pd.api.types.is_numeric_dtype(data[column]):
                        # Formato oficial usa ponto decimal; aceita vírgula em CSV legado.
                        values = data[column].astype("string").str.replace(",", ".", regex=False)
                        data[column] = pd.to_numeric(values, errors="coerce")
                    else:
                        data[column] = pd.to_numeric(data[column], errors="coerce")
            if "din_publicacao" in data.columns:
                data["din_publicacao"] = pd.to_datetime(data["din_publicacao"], errors="coerce")
            if data.empty:
                raise ValueError("Arquivo sem registros temporais válidos.")
            report.append({
                "Arquivo": name,
                "Ano": int(data["din_instante"].dt.year.mode().iloc[0]),
                "Linhas": len(data),
                "Datas inválidas": invalid,
                "Início": data["din_instante"].min(),
                "Fim": data["din_instante"].max(),
            })
            frames.append(data)
        except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
            errors.append(f"{name}: {exc}")
    if not frames:
        return ThermalResult(pd.DataFrame(), [], pd.DataFrame(report), errors, warnings)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["din_instante"] + (["din_publicacao"] if "din_publicacao" in combined.columns else []),
        kind="stable",
    )
    # Reedições publicadas do mesmo registro (usina / instante) não podem ser somadas.
    identity = ["din_instante", "id_subsistema", "nom_usina"]
    for column in ("cod_usinaplanejamento", "ceg"):
        if column in combined.columns:
            identity.append(column)
    before = len(combined)
    combined = combined.drop_duplicates(subset=identity, keep="last").reset_index(drop=True)
    duplicates = before - len(combined)
    if duplicates:
        warnings.append(f"{duplicates:,} registros duplicados substituídos pela última publicação.")
    metrics = [
        column for column in combined.columns
        if (column.startswith("val_prog") or column.startswith("val_verif")
            or column == "val_geracaodespachada")
        and pd.api.types.is_numeric_dtype(combined[column])
    ]
    metrics = [metric for metric in PRIMARY_METRICS if metric in metrics] + [
        metric for metric in metrics if metric not in PRIMARY_METRICS
    ]
    return ThermalResult(combined, metrics, pd.DataFrame(report), errors, warnings)


def aggregate_thermal(
    records: pd.DataFrame,
    granularity: Granularity,
    metrics: Iterable[str],
) -> pd.DataFrame:
    """Soma usinas por hora e calcula a média *das horas* no período.

    Não calcula média por linha/usina; isso criaria viés quando o número de
    usinas varia. Não soma entre si diferentes motivos de despacho, pois suas
    classificações podem se sobrepor.
    """
    metric_columns = [metric for metric in dict.fromkeys(metrics) if metric in records.columns]
    if records.empty or not metric_columns:
        return pd.DataFrame(columns=["Período", "Horas observadas", *metric_columns])
    if granularity not in FREQUENCIES:
        raise ValueError("Discretização inválida.")
    valid = records.dropna(subset=["din_instante"])
    if valid.empty:
        return pd.DataFrame(columns=["Período", "Horas observadas", *metric_columns])
    by_hour = valid.groupby("din_instante", sort=True)[metric_columns].sum(min_count=1)
    grouped = by_hour.resample(FREQUENCIES[granularity]).mean()
    coverage = by_hour.resample(FREQUENCIES[granularity]).size()
    grouped.insert(0, "Horas observadas", coverage)
    grouped = grouped[coverage.gt(0)]
    return grouped.rename_axis("Período").reset_index()
