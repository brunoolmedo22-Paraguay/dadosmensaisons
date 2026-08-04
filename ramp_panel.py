from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

import numpy as np
import pandas as pd

TIMESTAMP: Final = "din_instante"
LOAD: Final = "val_carga"
WIND: Final = "val_gereolica"
SOLAR: Final = "val_gersolar"
RAMP: Final = "ramp"
ABS_RAMP: Final = "abs_ramp"
SERIES_VALUE: Final = "series_value"
RampSeries = Literal["load", "net_solar", "net_solar_wind"]
RampUnit = Literal["mw", "percent"]
HeatMetric = Literal["mean_abs", "p95", "maximum", "frequency"]

SERIES_LABELS = {
    "load": "Carga",
    "net_solar": "Carga líquida sem solar",
    "net_solar_wind": "Carga líquida sem solar e eólica",
}


@dataclass(frozen=True)
class RampKpis:
    max_up: float
    max_down: float
    p95_year: int | None
    critical_hour: int | None
    growth_percent: float | None
    growth_basis: str


def prepare_ramps(
    hourly: pd.DataFrame,
    *,
    series: RampSeries = "load",
    unit: RampUnit = "mw",
    start_date: date | pd.Timestamp | None = None,
    end_date: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Calcula rampas apenas entre registros horários consecutivos."""
    required = {TIMESTAMP, LOAD}
    if hourly.empty or not required.issubset(hourly.columns):
        return pd.DataFrame()
    data = hourly.copy()
    data[TIMESTAMP] = pd.to_datetime(data[TIMESTAMP], errors="coerce")
    for column in (LOAD, WIND, SOLAR):
        if column not in data.columns:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=[TIMESTAMP, LOAD]).sort_values(TIMESTAMP, kind="stable")
    if start_date is not None:
        data = data.loc[data[TIMESTAMP].ge(pd.Timestamp(start_date))]
    if end_date is not None:
        data = data.loc[data[TIMESTAMP].lt(pd.Timestamp(end_date) + pd.Timedelta(days=1))]
    if data.empty:
        return pd.DataFrame()

    if series == "load":
        values = data[LOAD]
    elif series == "net_solar":
        values = data[LOAD] - data[SOLAR].fillna(0.0)
    elif series == "net_solar_wind":
        values = data[LOAD] - data[SOLAR].fillna(0.0) - data[WIND].fillna(0.0)
    else:
        raise ValueError(f"Série inválida: {series}")

    previous_time = data[TIMESTAMP].shift(1)
    previous_value = values.shift(1)
    consecutive = data[TIMESTAMP].sub(previous_time).eq(pd.Timedelta(hours=1))
    difference = values.sub(previous_value)
    if unit == "percent":
        denominator = previous_value.abs().where(previous_value.abs().gt(1e-9))
        difference = difference.div(denominator).mul(100.0)
    elif unit != "mw":
        raise ValueError(f"Unidade inválida: {unit}")
    difference = difference.where(consecutive)

    result = pd.DataFrame(
        {
            TIMESTAMP: data[TIMESTAMP],
            SERIES_VALUE: values,
            RAMP: difference,
        }
    ).dropna(subset=[RAMP])
    if result.empty:
        return result
    result[ABS_RAMP] = result[RAMP].abs()
    result["year"] = result[TIMESTAMP].dt.year.astype(int)
    result["hour"] = result[TIMESTAMP].dt.hour.astype(int)
    result["direction"] = np.where(result[RAMP].ge(0), "up", "down")
    return result.reset_index(drop=True)


def annual_severity(ramps: pd.DataFrame) -> pd.DataFrame:
    if ramps.empty:
        return pd.DataFrame(columns=["year", "max_up", "max_down", "p95_abs", "p99_abs"])
    grouped = ramps.groupby("year", observed=True)
    summary = grouped[RAMP].agg(
        max_up=lambda s: s[s.ge(0)].max() if s.ge(0).any() else np.nan,
        max_down=lambda s: s[s.lt(0)].min() if s.lt(0).any() else np.nan,
    )
    summary["p95_abs"] = grouped[ABS_RAMP].quantile(0.95)
    summary["p99_abs"] = grouped[ABS_RAMP].quantile(0.99)
    return summary.reset_index()


def annual_distribution(ramps: pd.DataFrame) -> pd.DataFrame:
    columns = ["year", "p05", "p25", "p50", "p75", "p95"]
    if ramps.empty:
        return pd.DataFrame(columns=columns)
    quantiles = ramps.groupby("year", observed=True)[RAMP].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack()
    quantiles.columns = ["p05", "p25", "p50", "p75", "p95"]
    return quantiles.reset_index()[columns]


def hourly_heatmap(
    ramps: pd.DataFrame,
    metric: HeatMetric = "p95",
    threshold: float | None = None,
) -> pd.DataFrame:
    if ramps.empty:
        return pd.DataFrame()
    grouped = ramps.groupby(["year", "hour"], observed=True)
    if metric == "mean_abs":
        table = grouped[ABS_RAMP].mean()
    elif metric == "p95":
        table = grouped[ABS_RAMP].quantile(0.95)
    elif metric == "maximum":
        table = grouped[ABS_RAMP].max()
    elif metric == "frequency":
        limit = float(threshold or 0.0)
        table = grouped[ABS_RAMP].apply(lambda s: float(s.ge(limit).mean() * 100.0))
    else:
        raise ValueError(f"Métrica inválida: {metric}")
    return table.unstack("hour").reindex(columns=range(24))


def ramp_kpis(ramps: pd.DataFrame) -> RampKpis:
    if ramps.empty:
        return RampKpis(np.nan, np.nan, None, None, None, "p95 do módulo")
    annual = annual_severity(ramps)
    p95_year = int(annual.loc[annual["p95_abs"].idxmax(), "year"]) if annual["p95_abs"].notna().any() else None
    hour_scores = ramps.groupby("hour", observed=True)[ABS_RAMP].quantile(0.95)
    critical_hour = int(hour_scores.idxmax()) if not hour_scores.empty else None
    counts = ramps.groupby("year", observed=True).size()
    complete_years = []
    for year, count in counts.items():
        expected = (8784 if pd.Timestamp(year=int(year), month=12, day=31).is_leap_year else 8760) - 1
        if int(count) >= int(expected * 0.90):
            complete_years.append(int(year))
    years = sorted(complete_years or annual["year"].dropna().astype(int).unique())
    growth = None
    if len(years) >= 2:
        block = min(3, max(1, len(years) // 2))
        first = annual.loc[annual["year"].isin(years[:block]), "p95_abs"].mean()
        last = annual.loc[annual["year"].isin(years[-block:]), "p95_abs"].mean()
        if pd.notna(first) and abs(float(first)) > 1e-12 and pd.notna(last):
            growth = (float(last) - float(first)) / abs(float(first)) * 100.0
    return RampKpis(
        max_up=float(ramps[RAMP].max()),
        max_down=float(ramps[RAMP].min()),
        p95_year=p95_year,
        critical_hour=critical_hour,
        growth_percent=growth,
        growth_basis="p95 do módulo (primeiros × últimos 3 anos, quando disponíveis)",
    )


def filter_direction(ramps: pd.DataFrame, direction: str, descending_as_abs: bool = False) -> pd.DataFrame:
    if ramps.empty:
        return ramps.copy()
    result = ramps.copy()
    if direction == "up":
        result = result.loc[result[RAMP].ge(0)]
    elif direction == "down":
        result = result.loc[result[RAMP].lt(0)]
        if descending_as_abs:
            result[RAMP] = result[RAMP].abs()
    elif direction == "absolute":
        result[RAMP] = result[ABS_RAMP]
    elif direction != "both":
        raise ValueError(f"Direção inválida: {direction}")
    return result.reset_index(drop=True)
