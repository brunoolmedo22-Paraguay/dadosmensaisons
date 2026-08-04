from __future__ import annotations

from datetime import date
from typing import Final, Literal

import numpy as np
import pandas as pd

TIMESTAMP: Final = "timestamp"
VALUE: Final = "value"
UNIT: Final = "unit"
SOURCE: Final = "source"
EVENT: Final = "event_type"

EventType = Literal[
    "max_load", "min_net_load", "max_ramp_up", "max_ramp_down", "max_ramp_abs",
    "max_solar_share", "max_wind_share", "max_vre_share", "max_ear_drop",
    "max_ear_rise", "ena_positive_deviation", "ena_negative_deviation",
    "ena_absolute_deviation", "max_import", "max_export",
]


def _hourly_base(hourly: pd.DataFrame, start_date: date | None, end_date: date | None) -> pd.DataFrame:
    if hourly.empty or "din_instante" not in hourly.columns:
        return pd.DataFrame()
    data = hourly.copy()
    data["din_instante"] = pd.to_datetime(data["din_instante"], errors="coerce")
    for col in ("val_carga", "val_gersolar", "val_gereolica", "val_gerhidraulica", "val_gertermica", "val_intercambio"):
        if col not in data.columns:
            data[col] = 0.0
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["din_instante", "val_carga"]).sort_values("din_instante", kind="stable")
    if start_date is not None:
        data = data.loc[data["din_instante"].ge(pd.Timestamp(start_date))]
    if end_date is not None:
        data = data.loc[data["din_instante"].lt(pd.Timestamp(end_date) + pd.Timedelta(days=1))]
    data["net_load_solar"] = data["val_carga"] - data["val_gersolar"].fillna(0)
    data["net_load"] = data["net_load_solar"] - data["val_gereolica"].fillna(0)
    denom = data["val_carga"].where(data["val_carga"].abs().gt(1e-9))
    data["solar_share"] = data["val_gersolar"].div(denom).mul(100)
    data["wind_share"] = data["val_gereolica"].div(denom).mul(100)
    data["vre_share"] = data["val_gersolar"].add(data["val_gereolica"]).div(denom).mul(100)
    return data


def _event_frame(values: pd.Series, timestamps: pd.Series, event_type: str, unit: str, source: str) -> pd.DataFrame:
    frame = pd.DataFrame({TIMESTAMP: pd.to_datetime(timestamps), VALUE: pd.to_numeric(values, errors="coerce")}).dropna()
    frame[EVENT] = event_type
    frame[UNIT] = unit
    frame[SOURCE] = source
    return frame


def event_candidates(
    event_type: EventType,
    *,
    hourly: pd.DataFrame = pd.DataFrame(),
    ear_daily: pd.DataFrame = pd.DataFrame(),
    ena_daily: pd.DataFrame = pd.DataFrame(),
    start_date: date | None = None,
    end_date: date | None = None,
    net_load_mode: str = "solar_wind",
) -> pd.DataFrame:
    data = _hourly_base(hourly, start_date, end_date)
    net_column = "net_load_solar" if net_load_mode == "solar" else "net_load"
    if not data.empty:
        previous_time = data["din_instante"].shift()
        consecutive = data["din_instante"].sub(previous_time).eq(pd.Timedelta(hours=1))
        data["ramp"] = data[net_column].diff().where(consecutive)
    if event_type == "max_load":
        return _event_frame(data["val_carga"], data["din_instante"], event_type, "MWmed", "BALANCO")
    if event_type == "min_net_load":
        return _event_frame(data[net_column], data["din_instante"], event_type, "MWmed", "BALANCO")
    if event_type in {"max_ramp_up", "max_ramp_down", "max_ramp_abs"}:
        values = data["ramp"]
        if event_type == "max_ramp_up":
            values = values.where(values.ge(0))
        elif event_type == "max_ramp_down":
            values = values.where(values.lt(0))
        else:
            values = values.abs()
        return _event_frame(values, data["din_instante"], event_type, "MW/h", "BALANCO")
    if event_type == "max_solar_share":
        return _event_frame(data["solar_share"], data["din_instante"], event_type, "%", "BALANCO")
    if event_type == "max_wind_share":
        return _event_frame(data["wind_share"], data["din_instante"], event_type, "%", "BALANCO")
    if event_type == "max_vre_share":
        return _event_frame(data["vre_share"], data["din_instante"], event_type, "%", "BALANCO")
    if event_type in {"max_import", "max_export"}:
        vals = data["val_intercambio"]
        if event_type == "max_import":
            vals = vals.where(vals.ge(0))
        else:
            vals = (-vals.where(vals.lt(0)))
        return _event_frame(vals, data["din_instante"], event_type, "MWmed", "BALANCO")

    if event_type in {"max_ear_drop", "max_ear_rise"}:
        if ear_daily.empty or "ear_data" not in ear_daily.columns:
            return pd.DataFrame()
        frame = ear_daily.copy()
        frame["ear_data"] = pd.to_datetime(frame["ear_data"], errors="coerce")
        frame["ear_verif_subsistema_percentual"] = pd.to_numeric(frame.get("ear_verif_subsistema_percentual"), errors="coerce")
        frame = frame.dropna(subset=["ear_data", "ear_verif_subsistema_percentual"]).sort_values("ear_data")
        if start_date is not None: frame = frame.loc[frame["ear_data"].ge(pd.Timestamp(start_date))]
        if end_date is not None: frame = frame.loc[frame["ear_data"].lt(pd.Timestamp(end_date)+pd.Timedelta(days=1))]
        delta = frame["ear_verif_subsistema_percentual"].diff()
        values = -delta.where(delta.lt(0)) if event_type == "max_ear_drop" else delta.where(delta.gt(0))
        return _event_frame(values, frame["ear_data"], event_type, "p.p./dia", "EAR")

    if event_type.startswith("ena_"):
        if ena_daily.empty or "ena_data" not in ena_daily.columns:
            return pd.DataFrame()
        frame = ena_daily.copy()
        frame["ena_data"] = pd.to_datetime(frame["ena_data"], errors="coerce")
        frame["ena_bruta_regiao_percentualmlt"] = pd.to_numeric(frame.get("ena_bruta_regiao_percentualmlt"), errors="coerce")
        frame = frame.dropna(subset=["ena_data", "ena_bruta_regiao_percentualmlt"]).sort_values("ena_data")
        if start_date is not None: frame = frame.loc[frame["ena_data"].ge(pd.Timestamp(start_date))]
        if end_date is not None: frame = frame.loc[frame["ena_data"].lt(pd.Timestamp(end_date)+pd.Timedelta(days=1))]
        deviation = frame["ena_bruta_regiao_percentualmlt"] - 100.0
        if event_type == "ena_positive_deviation": values = deviation.where(deviation.gt(0))
        elif event_type == "ena_negative_deviation": values = -deviation.where(deviation.lt(0))
        else: values = deviation.abs()
        return _event_frame(values, frame["ena_data"], event_type, "p.p.", "ENA")
    raise ValueError(f"Evento inválido: {event_type}")


def anomaly_score(values: pd.Series, method: str) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    if method == "none": return series.abs()
    if method == "zscore":
        std = series.std(ddof=0)
        return (series - series.mean()).abs().div(std if pd.notna(std) and std > 0 else np.nan)
    if method == "iqr":
        q1, q3 = series.quantile([0.25, 0.75])
        iqr = q3 - q1
        center = (q1 + q3) / 2
        return (series - center).abs().div(iqr if pd.notna(iqr) and iqr > 0 else np.nan)
    if method == "moving":
        baseline = series.rolling(168, min_periods=24, center=True).mean()
        return (series - baseline).abs()
    raise ValueError(f"Método inválido: {method}")


def rank_events(candidates: pd.DataFrame, n: int = 10, *, ascending: bool = False, anomaly_method: str = "none") -> pd.DataFrame:
    if candidates.empty: return pd.DataFrame()
    result = candidates.copy()
    result["score"] = anomaly_score(result[VALUE], anomaly_method)
    if anomaly_method == "none":
        result = result.sort_values(VALUE, ascending=ascending, kind="stable")
    else:
        result = result.sort_values("score", ascending=False, kind="stable")
    result = result.head(int(n)).reset_index(drop=True)
    result.insert(0, "rank", range(1, len(result)+1))
    result["context"] = result[TIMESTAMP].dt.strftime("%d/%m/%Y %H:%M")
    return result


def event_window(
    selected_timestamp: pd.Timestamp,
    *,
    source: str,
    hourly: pd.DataFrame = pd.DataFrame(),
    daily: pd.DataFrame = pd.DataFrame(),
    hours: int = 24,
    days: int = 15,
) -> pd.DataFrame:
    center = pd.Timestamp(selected_timestamp)
    if source == "BALANCO":
        data = _hourly_base(hourly, None, None)
        return data.loc[data["din_instante"].between(center-pd.Timedelta(hours=hours), center+pd.Timedelta(hours=hours))].copy()
    date_col = "ear_data" if source == "EAR" else "ena_data"
    if daily.empty or date_col not in daily.columns: return pd.DataFrame()
    data = daily.copy(); data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    return data.loc[data[date_col].between(center-pd.Timedelta(days=days), center+pd.Timedelta(days=days))].copy()


def csv_bytes(data: pd.DataFrame) -> bytes:
    export = data.copy()
    for column in export.columns:
        if pd.api.types.is_datetime64_any_dtype(export[column]):
            export[column] = pd.to_datetime(export[column]).dt.strftime("%d/%m/%Y %H:%M")
    return export.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")
