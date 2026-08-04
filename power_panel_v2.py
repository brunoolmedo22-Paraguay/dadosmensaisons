from __future__ import annotations

from collections.abc import Iterable
from typing import Final

import pandas as pd


PERIOD_COLUMN: Final = "__period_start"
LOAD_COLUMN: Final = "Carga (MWmed)"
HYDRO_COLUMN: Final = "Geração hidráulica (MWmed)"
THERMAL_COLUMN: Final = "Geração térmica (MWmed)"
WIND_COLUMN: Final = "Geração eólica (MWmed)"
SOLAR_COLUMN: Final = "Geração solar (MWmed)"
DUCK_CURVE_COLUMN: Final = "Curva de pato (MWmed)"
VARIABLE_RENEWABLE_COLUMN: Final = "Eólica + Solar (MWmed)"
TOTAL_GENERATION_COLUMN: Final = "Geração total das fontes (MWmed)"
BALANCE_DIFFERENCE_COLUMN: Final = "Diferença carga − fontes (MWmed)"
PARTICIPATION_SOURCE_COLUMN: Final = "Fonte"
PARTICIPATION_VALUE_COLUMN: Final = "Participação (MWmed)"
PARTICIPATION_PERCENT_COLUMN: Final = "Participação (%)"

GENERATION_COLUMNS: Final[tuple[str, ...]] = (
    HYDRO_COLUMN,
    THERMAL_COLUMN,
    WIND_COLUMN,
    SOLAR_COLUMN,
)
SOURCE_KEYS: Final[tuple[str, ...]] = ("hydro", "thermal", "wind", "solar")
SOURCE_COLUMN_BY_KEY: Final[dict[str, str]] = {
    "hydro": HYDRO_COLUMN,
    "thermal": THERMAL_COLUMN,
    "wind": WIND_COLUMN,
    "solar": SOLAR_COLUMN,
}


def prepare_power_panel_data(summary: pd.DataFrame) -> pd.DataFrame:
    """Prepara carga, curva de pato e componentes sem alterar o resumo original.

    A curva de pato é sempre definida como a carga líquida após a geração eólica
    e solar. As fontes ausentes são tratadas como zero, mas a carga e o instante
    são obrigatórios.
    """
    if summary.empty or PERIOD_COLUMN not in summary.columns or LOAD_COLUMN not in summary.columns:
        return pd.DataFrame()

    result = summary.copy()
    result[PERIOD_COLUMN] = pd.to_datetime(result[PERIOD_COLUMN], errors="coerce")
    result[LOAD_COLUMN] = pd.to_numeric(result[LOAD_COLUMN], errors="coerce")

    for column in GENERATION_COLUMNS:
        if column not in result.columns:
            result[column] = 0.0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)

    result = result.dropna(subset=[PERIOD_COLUMN, LOAD_COLUMN]).sort_values(
        PERIOD_COLUMN,
        kind="stable",
    )
    if result.empty:
        return result

    result[VARIABLE_RENEWABLE_COLUMN] = result[WIND_COLUMN] + result[SOLAR_COLUMN]
    result[DUCK_CURVE_COLUMN] = result[LOAD_COLUMN] - result[VARIABLE_RENEWABLE_COLUMN]
    result[TOTAL_GENERATION_COLUMN] = result[list(GENERATION_COLUMNS)].sum(axis=1)
    result[BALANCE_DIFFERENCE_COLUMN] = (
        result[LOAD_COLUMN] - result[TOTAL_GENERATION_COLUMN]
    )
    return result


def prepare_source_participation(summary: pd.DataFrame) -> pd.DataFrame:
    """Converte o resumo temporal em formato longo para participação por fonte.

    O percentual de cada fonte usa como denominador a soma da geração hidráulica,
    térmica, eólica e solar no mesmo período. Períodos sem geração positiva são
    descartados para evitar participações indefinidas.
    """
    if summary.empty or PERIOD_COLUMN not in summary.columns:
        return pd.DataFrame()

    frame = summary.copy()
    frame[PERIOD_COLUMN] = pd.to_datetime(frame[PERIOD_COLUMN], errors="coerce")
    for column in GENERATION_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        frame[column] = frame[column].clip(lower=0.0)

    frame = frame.dropna(subset=[PERIOD_COLUMN]).sort_values(PERIOD_COLUMN, kind="stable")
    if frame.empty:
        return pd.DataFrame()

    frame[TOTAL_GENERATION_COLUMN] = frame[list(GENERATION_COLUMNS)].sum(axis=1)
    frame = frame.loc[frame[TOTAL_GENERATION_COLUMN].gt(0.0)].copy()
    if frame.empty:
        return pd.DataFrame()

    column_to_source = {column: key for key, column in SOURCE_COLUMN_BY_KEY.items()}
    long_data = frame.melt(
        id_vars=[PERIOD_COLUMN, TOTAL_GENERATION_COLUMN],
        value_vars=list(GENERATION_COLUMNS),
        var_name="__source_column",
        value_name=PARTICIPATION_VALUE_COLUMN,
    )
    long_data[PARTICIPATION_SOURCE_COLUMN] = long_data["__source_column"].map(column_to_source)
    long_data[PARTICIPATION_PERCENT_COLUMN] = (
        long_data[PARTICIPATION_VALUE_COLUMN]
        / long_data[TOTAL_GENERATION_COLUMN]
        * 100.0
    )
    return long_data[
        [
            PERIOD_COLUMN,
            PARTICIPATION_SOURCE_COLUMN,
            PARTICIPATION_VALUE_COLUMN,
            PARTICIPATION_PERCENT_COLUMN,
            TOTAL_GENERATION_COLUMN,
        ]
    ].reset_index(drop=True)


def normalize_source_order(values: Iterable[str]) -> tuple[str, ...]:
    """Retorna as quatro fontes sem repetição, preservando a ordem válida."""
    ordered: list[str] = []
    for value in values:
        if value in SOURCE_KEYS and value not in ordered:
            ordered.append(value)
    for value in SOURCE_KEYS:
        if value not in ordered:
            ordered.append(value)
    return tuple(ordered)


def material_balance_difference(data: pd.DataFrame) -> bool:
    """Indica se a diferença carga-fontes é relevante para exibir uma nota."""
    if data.empty or BALANCE_DIFFERENCE_COLUMN not in data.columns:
        return False
    load_scale = data[LOAD_COLUMN].abs().median()
    difference = data[BALANCE_DIFFERENCE_COLUMN].abs().median()
    if pd.isna(difference):
        return False
    tolerance = max(1.0, float(load_scale or 0.0) * 0.01)
    return float(difference) > tolerance
