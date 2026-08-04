from __future__ import annotations

import calendar
from datetime import date
from typing import Final, Sequence

import numpy as np
import pandas as pd

TIMESTAMP: Final = "din_instante"
SOURCE_COLUMNS: Final[dict[str, str]] = {
    "hydro": "val_gerhidraulica",
    "thermal": "val_gertermica",
    "wind": "val_gereolica",
    "solar": "val_gersolar",
}
LOAD_COLUMN: Final = "val_carga"
INTERCHANGE_COLUMN: Final = "val_intercambio"


def annual_matrix(
    hourly: pd.DataFrame,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    sources: Sequence[str] = ("hydro", "thermal", "wind", "solar"),
    base_year: int | None = None,
    measure: str = "mean",
) -> pd.DataFrame:
    if hourly.empty or TIMESTAMP not in hourly.columns:
        return pd.DataFrame()
    data = hourly.copy()
    data[TIMESTAMP] = pd.to_datetime(data[TIMESTAMP], errors="coerce")
    columns = [SOURCE_COLUMNS[s] for s in sources if s in SOURCE_COLUMNS]
    for col in [*columns, LOAD_COLUMN, INTERCHANGE_COLUMN]:
        if col not in data.columns: data[col] = 0.0
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=[TIMESTAMP]).sort_values(TIMESTAMP)
    if start_date is not None: data = data.loc[data[TIMESTAMP].ge(pd.Timestamp(start_date))]
    if end_date is not None: data = data.loc[data[TIMESTAMP].lt(pd.Timestamp(end_date)+pd.Timedelta(days=1))]
    if data.empty: return pd.DataFrame()
    data["year"] = data[TIMESTAMP].dt.year.astype(int)
    metrics = [*columns, LOAD_COLUMN, INTERCHANGE_COLUMN]
    annual = data.groupby("year", observed=True)[metrics].mean().reset_index()
    hours = data.groupby("year", observed=True)[TIMESTAMP].nunique()
    annual["hours_with_data"] = annual["year"].map(hours)
    annual["hours_expected"] = annual["year"].map(lambda y: 8784 if calendar.isleap(int(y)) else 8760)
    annual["coverage"] = annual["hours_with_data"] / annual["hours_expected"] * 100.0
    annual["complete"] = annual["coverage"].ge(99.5)
    if measure == "energy":
        for column in metrics:
            annual[column] = annual[column] * annual["hours_with_data"] / 1000.0
    elif measure != "mean":
        raise ValueError(f"Métrica anual inválida: {measure}")
    annual["measure"] = measure
    annual["generation_total"] = annual[columns].sum(axis=1) if columns else 0.0
    for source, col in SOURCE_COLUMNS.items():
        if col not in annual.columns: annual[col] = 0.0
        annual[f"share_{source}"] = annual[col].div(annual["generation_total"].replace(0, np.nan)).mul(100)
        annual[f"growth_{source}"] = annual[col].pct_change(fill_method=None).mul(100)
        first_valid = annual[col].replace(0, np.nan).dropna()
        base_value = float(first_valid.iloc[0]) if not first_valid.empty else np.nan
        annual[f"cumulative_{source}"] = annual[col].div(base_value).sub(1).mul(100) if pd.notna(base_value) else np.nan
    annual["vre"] = annual[SOURCE_COLUMNS["wind"]] + annual[SOURCE_COLUMNS["solar"]]
    annual["vre_share_load"] = annual["vre"].div(annual[LOAD_COLUMN].replace(0, np.nan)).mul(100)
    annual["hydro_share"] = annual["share_hydro"]
    annual["thermal_share"] = annual["share_thermal"]

    valid_years = annual["year"].astype(int).tolist()
    selected_base = int(base_year) if base_year in valid_years else (valid_years[0] if valid_years else None)
    if selected_base is not None:
        base_row = annual.loc[annual["year"].eq(selected_base)].iloc[0]
        for source, col in SOURCE_COLUMNS.items():
            base = float(base_row[col])
            annual[f"index_{source}"] = annual[col].div(base if abs(base)>1e-12 else np.nan).mul(100)
            annual[f"difference_{source}"] = annual[col] - base
        base_load = float(base_row[LOAD_COLUMN])
        annual["index_load"] = annual[LOAD_COLUMN].div(base_load if abs(base_load)>1e-12 else np.nan).mul(100)
        annual["difference_load"] = annual[LOAD_COLUMN] - base_load
    annual["base_year"] = selected_base
    return annual.reset_index(drop=True)


def matrix_kpis(annual: pd.DataFrame) -> dict[str, object]:
    if annual.empty: return {}
    first, last = annual.iloc[0], annual.iloc[-1]
    growths: dict[str, float] = {}
    for source, col in SOURCE_COLUMNS.items():
        initial = float(first[col]); final = float(last[col])
        growths[source] = (final-initial)/abs(initial)*100 if abs(initial)>1e-12 else np.nan
    finite = {k:v for k,v in growths.items() if pd.notna(v)}
    fastest = max(finite, key=finite.get) if finite else None
    participation_change = float(last["vre_share_load"] - first["vre_share_load"])
    changes = annual[[f"growth_{s}" for s in SOURCE_COLUMNS]].abs().sum(axis=1, min_count=1)
    transform_year = int(annual.loc[changes.idxmax(), "year"]) if changes.notna().any() else None
    return {
        "fastest_source": fastest,
        "solar_growth": growths.get("solar"),
        "wind_growth": growths.get("wind"),
        "thermal_change": growths.get("thermal"),
        "hydro_change": growths.get("hydro"),
        "vre_participation_change": participation_change,
        "transformation_year": transform_year,
    }


def first_threshold_year(annual: pd.DataFrame, source: str, threshold: float) -> int | None:
    column = f"share_{source}"
    if annual.empty or column not in annual.columns: return None
    hits = annual.loc[annual[column].ge(float(threshold)), "year"]
    return int(hits.iloc[0]) if not hits.empty else None


def annual_csv_bytes(annual: pd.DataFrame) -> bytes:
    return annual.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")
