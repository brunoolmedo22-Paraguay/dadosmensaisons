from __future__ import annotations

from datetime import date
from typing import Literal, Sequence

import pandas as pd

Granularity = Literal["daily", "monthly", "yearly"]
DataSource = Literal["BALANCO", "EAR"]

DATA_SOURCES: tuple[DataSource, ...] = ("BALANCO", "EAR")
PERIOD_COLUMNS: dict[Granularity, list[str]] = {
    "daily": ["Data"],
    "monthly": ["Ano", "Mês"],
    "yearly": ["Ano"],
}

BALANCE_QUALITY_RENAMES = {
    "Cobertura (%)": "Cobertura Balanço (%)",
    "Status do período": "Status Balanço",
}
EAR_QUALITY_RENAMES = {
    "Cobertura (%)": "Cobertura EAR (%)",
    "Status do período": "Status EAR",
}


def combine_summaries(
    balance_summary: pd.DataFrame,
    ear_summary: pd.DataFrame,
    granularity: Granularity,
    selected_sources: Sequence[DataSource],
    balance_metrics: Sequence[str] = (),
    ear_metrics: Sequence[str] = (),
) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    """Une as bases selecionadas em uma única série temporal.

    O merge é externo para não eliminar um período existente em apenas uma base.
    Retorna a tabela unificada, as métricas visíveis, as colunas de cobertura e
    as colunas de status.
    """
    if granularity not in PERIOD_COLUMNS:
        raise ValueError(f"Discretização inválida: {granularity}")

    selected = [source for source in DATA_SOURCES if source in selected_sources]
    if not selected:
        return pd.DataFrame(), [], [], []

    frames: list[pd.DataFrame] = []
    metric_columns: list[str] = []
    coverage_columns: list[str] = []
    status_columns: list[str] = []

    if "BALANCO" in selected and not balance_summary.empty:
        balance = _prepare_source_frame(
            balance_summary,
            metric_candidates=balance_metrics,
            quality_renames=BALANCE_QUALITY_RENAMES,
        )
        frames.append(balance)
        metric_columns.extend(
            column for column in balance_metrics if column in balance.columns
        )
        coverage_columns.extend(
            column
            for column in ["Cobertura Balanço (%)"]
            if column in balance.columns
        )
        status_columns.extend(
            column for column in ["Status Balanço"] if column in balance.columns
        )

    if "EAR" in selected and not ear_summary.empty:
        ear = _prepare_source_frame(
            ear_summary,
            metric_candidates=ear_metrics,
            quality_renames=EAR_QUALITY_RENAMES,
        )
        frames.append(ear)
        metric_columns.extend(column for column in ear_metrics if column in ear.columns)
        coverage_columns.extend(
            column for column in ["Cobertura EAR (%)"] if column in ear.columns
        )
        status_columns.extend(
            column for column in ["Status EAR"] if column in ear.columns
        )

    if not frames:
        return pd.DataFrame(), [], [], []

    unified = frames[0]
    for frame in frames[1:]:
        unified = unified.merge(frame, on="__period_start", how="outer", sort=True)

    unified = unified.sort_values("__period_start", kind="stable").reset_index(drop=True)
    unified = _add_period_columns(unified, granularity)

    period_columns = PERIOD_COLUMNS[granularity]
    support_columns = [
        column
        for column in [
            "Horas com dados",
            "Horas esperadas",
            "Dias com dados",
            "Dias esperados",
            *coverage_columns,
            *status_columns,
        ]
        if column in unified.columns
    ]
    ordered = [
        *period_columns,
        "__period_start",
        *metric_columns,
        *support_columns,
    ]
    remaining = [column for column in unified.columns if column not in ordered]
    unified = unified[[*ordered, *remaining]]
    return unified, metric_columns, coverage_columns, status_columns


def build_unified_csv_export(data: pd.DataFrame) -> pd.DataFrame:
    """Gera o CSV exatamente com as colunas visíveis da tabela."""
    export = data.drop(columns=["Mês nº", "__period_start"], errors="ignore").copy()
    if "Data" in export.columns:
        export["Data"] = pd.to_datetime(export["Data"], errors="coerce").dt.strftime(
            "%d/%m/%Y"
        )
    return export


def source_date_bounds(
    balance_data: pd.DataFrame,
    ear_data: pd.DataFrame,
    selected_sources: Sequence[DataSource],
) -> tuple[date, date] | None:
    """Retorna o menor e o maior dia disponíveis nas bases selecionadas."""
    dates: list[pd.Series] = []
    if "BALANCO" in selected_sources and not balance_data.empty:
        if "din_instante" in balance_data.columns:
            dates.append(pd.to_datetime(balance_data["din_instante"], errors="coerce"))
    if "EAR" in selected_sources and not ear_data.empty:
        if "ear_data" in ear_data.columns:
            dates.append(pd.to_datetime(ear_data["ear_data"], errors="coerce"))
    if not dates:
        return None
    combined = pd.concat(dates, ignore_index=True).dropna()
    if combined.empty:
        return None
    return combined.min().date(), combined.max().date()


def _prepare_source_frame(
    summary: pd.DataFrame,
    metric_candidates: Sequence[str],
    quality_renames: dict[str, str],
) -> pd.DataFrame:
    frame = summary.copy().rename(columns=quality_renames)
    if "__period_start" not in frame.columns:
        raise ValueError("A série não contém a coluna temporal interna.")

    keep = ["__period_start"]
    keep.extend(column for column in metric_candidates if column in frame.columns)
    keep.extend(
        column
        for column in [
            "Horas com dados",
            "Horas esperadas",
            "Dias com dados",
            "Dias esperados",
            *quality_renames.values(),
        ]
        if column in frame.columns
    )
    return frame[keep].copy()


def _add_period_columns(data: pd.DataFrame, granularity: Granularity) -> pd.DataFrame:
    result = data.copy()
    timestamps = pd.to_datetime(result["__period_start"], errors="coerce")
    if granularity == "daily":
        result["Data"] = timestamps.dt.date
    elif granularity == "monthly":
        result["Ano"] = timestamps.dt.year.astype("Int64")
        result["Mês nº"] = timestamps.dt.month.astype("Int64")
        result["Mês"] = result["Mês nº"].map(
            {
                1: "Janeiro",
                2: "Fevereiro",
                3: "Março",
                4: "Abril",
                5: "Maio",
                6: "Junho",
                7: "Julho",
                8: "Agosto",
                9: "Setembro",
                10: "Outubro",
                11: "Novembro",
                12: "Dezembro",
            }
        )
    else:
        result["Ano"] = timestamps.dt.year.astype("Int64")
    return result
