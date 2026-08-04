from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import pandas as pd


MONTH_NAMES = {
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

METRIC_LABELS = {
    "val_gerhidraulica": "Geração hidráulica (MWmed)",
    "val_gertermica": "Geração térmica (MWmed)",
    "val_gereolica": "Geração eólica (MWmed)",
    "val_gersolar": "Geração solar (MWmed)",
    "val_carga": "Carga (MWmed)",
    "val_intercambio": "Intercâmbio (MWmed)",
}

CSV_EXPORT_COLUMNS = [
    "Ano",
    "Mês",
    *METRIC_LABELS.values(),
]

Granularity = Literal["hourly", "daily", "monthly", "yearly"]

GRANULARITY_PERIOD_COLUMNS: dict[Granularity, list[str]] = {
    "hourly": ["Data e hora"],
    "daily": ["Data"],
    "monthly": ["Ano", "Mês"],
    "yearly": ["Ano"],
}

COLUMN_ALIASES = {
    "id_subsistema": {
        "id_subsistema",
        "idsubsistema",
        "cod_subsistema",
        "codigo_subsistema",
    },
    "nom_subsistema": {
        "nom_subsistema",
        "nome_subsistema",
        "subsistema",
    },
    "din_instante": {
        "din_instante",
        "data_hora",
        "datahora",
        "instante",
        "timestamp",
    },
}

REPORT_COLUMNS = [
    "Arquivo",
    "Ano",
    "Período lido",
    "Linhas horárias do SIN",
    "Meses",
    "Duplicatas removidas",
    "Situação",
]


class WorkbookError(ValueError):
    """Erro legível para um arquivo que não segue o formato esperado."""


@dataclass
class ProcessingResult:
    monthly: pd.DataFrame
    file_report: pd.DataFrame
    warnings: list[str]
    errors: list[str]
    metric_columns: list[str]
    hourly_rows: int
    hourly: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_csv_export(data: pd.DataFrame) -> pd.DataFrame:
    """Retorna somente as colunas finais solicitadas para o CSV."""
    export = data.copy()
    for column in CSV_EXPORT_COLUMNS:
        if column not in export.columns:
            export[column] = pd.NA
    return export[CSV_EXPORT_COLUMNS]


def available_subsystems(hourly: pd.DataFrame) -> list[tuple[str, str]]:
    """Lista subsistemas disponíveis como pares ``(chave, rótulo)``."""
    if hourly.empty:
        return []

    if "__subsystem_key" not in hourly.columns:
        return [("SIN", "SIN")]

    columns = ["__subsystem_key"]
    if "__subsystem_label" in hourly.columns:
        columns.append("__subsystem_label")
    options = hourly[columns].dropna(subset=["__subsystem_key"])
    labels_by_key: dict[str, str] = {}
    for row in options.itertuples(index=False, name=None):
        key = str(row[0]).strip()
        if not key:
            continue
        label = str(row[1]).strip() if len(row) > 1 and pd.notna(row[1]) else key
        current = labels_by_key.get(key)
        if current is None or (current == key and label != key):
            labels_by_key[key] = label or key

    return sorted(
        labels_by_key.items(),
        key=lambda item: (item[0] != "SIN", item[1].casefold()),
    )


def filter_hourly_by_subsystem(
    hourly: pd.DataFrame,
    subsystem_key: str,
) -> pd.DataFrame:
    """Filtra a série horária por subsistema sem alterar as colunas de dados."""
    if hourly.empty:
        return hourly.copy()
    if "__subsystem_key" not in hourly.columns:
        return hourly.copy() if subsystem_key == "SIN" else hourly.iloc[0:0].copy()
    return hourly.loc[hourly["__subsystem_key"].eq(subsystem_key)].copy()


def build_granular_csv_export(
    data: pd.DataFrame,
    granularity: Granularity,
) -> pd.DataFrame:
    """Monta o CSV correspondente à discretização exibida."""
    if granularity not in GRANULARITY_PERIOD_COLUMNS:
        raise ValueError(f"Discretização inválida: {granularity}")

    export = data.copy()
    period_columns = GRANULARITY_PERIOD_COLUMNS[granularity]
    known_metrics = list(METRIC_LABELS.values())
    extra_metrics = [
        column
        for column in export.columns
        if column.endswith(" (média)") and column not in known_metrics
    ]

    for column in [*period_columns, *known_metrics]:
        if column not in export.columns:
            export[column] = pd.NA

    if "Data e hora" in export.columns:
        timestamps = pd.to_datetime(export["Data e hora"], errors="coerce")
        export["Data e hora"] = timestamps.dt.strftime("%d/%m/%Y %H:%M")
    if "Data" in export.columns:
        dates = pd.to_datetime(export["Data"], errors="coerce")
        export["Data"] = dates.dt.strftime("%d/%m/%Y")

    return export[[*period_columns, *known_metrics, *extra_metrics]]


def build_period_summary(
    hourly: pd.DataFrame,
    granularity: Granularity,
    start_date: date | pd.Timestamp | None = None,
    end_date: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Agrega a série horária nas discretizações disponíveis na interface."""
    if granularity not in GRANULARITY_PERIOD_COLUMNS:
        raise ValueError(f"Discretização inválida: {granularity}")
    if hourly.empty or "din_instante" not in hourly.columns:
        return pd.DataFrame()

    data = hourly.copy()
    data["din_instante"] = pd.to_datetime(data["din_instante"], errors="coerce")
    data = data.dropna(subset=["din_instante"])
    if data.empty:
        return pd.DataFrame()

    if start_date is not None:
        start = _timestamp_boundary(data["din_instante"], start_date)
        data = data.loc[data["din_instante"].ge(start)]
    if end_date is not None:
        end = _timestamp_boundary(
            data["din_instante"],
            end_date,
        ) + pd.Timedelta(1, unit="D")
        data = data.loc[data["din_instante"].lt(end)]
    if data.empty:
        return pd.DataFrame()

    metric_columns = _ordered_metrics(
        [
            column
            for column in data.columns
            if column.startswith("val_") and data[column].notna().any()
        ]
    )
    if not metric_columns:
        return pd.DataFrame()

    if granularity == "hourly":
        data["__period_start"] = data["din_instante"].dt.floor("h")
    elif granularity == "daily":
        data["__period_start"] = data["din_instante"].dt.floor("D")
    elif granularity == "monthly":
        data["__period_start"] = (
            data["din_instante"].dt.to_period("M").dt.to_timestamp()
        )
    else:
        data["__period_start"] = (
            data["din_instante"].dt.to_period("Y").dt.to_timestamp()
        )

    grouped = data.groupby("__period_start", sort=True, observed=True)
    means = grouped[metric_columns].mean()
    hours = grouped["din_instante"].nunique().rename("Horas com dados")
    summary = means.join(hours).reset_index()
    summary["Horas esperadas"] = summary["__period_start"].map(
        lambda timestamp: _expected_hours(pd.Timestamp(timestamp), granularity)
    )
    summary["Cobertura (%)"] = (
        summary["Horas com dados"] / summary["Horas esperadas"] * 100
    ).round(1)
    summary["Status do período"] = summary.apply(
        lambda row: _coverage_status(
            int(row["Horas com dados"]),
            int(row["Horas esperadas"]),
        ),
        axis=1,
    )

    if granularity == "hourly":
        summary["Data e hora"] = summary["__period_start"]
    elif granularity == "daily":
        summary["Data"] = summary["__period_start"].dt.date
    elif granularity == "monthly":
        summary["Ano"] = summary["__period_start"].dt.year.astype(int)
        summary["Mês nº"] = summary["__period_start"].dt.month.astype(int)
        summary["Mês"] = summary["Mês nº"].map(MONTH_NAMES)
    else:
        summary["Ano"] = summary["__period_start"].dt.year.astype(int)

    summary = summary.rename(
        columns={column: _metric_label(column) for column in metric_columns}
    )
    display_metrics = [_metric_label(column) for column in metric_columns]
    period_columns = GRANULARITY_PERIOD_COLUMNS[granularity]
    internal_columns = ["__period_start"]
    if granularity == "monthly":
        internal_columns.append("Mês nº")
    ordered_columns = [
        *period_columns,
        *internal_columns,
        "Horas com dados",
        "Horas esperadas",
        "Cobertura (%)",
        "Status do período",
        *display_metrics,
    ]
    summary = summary[ordered_columns].sort_values(
        "__period_start",
        kind="stable",
    )
    summary[display_metrics] = summary[display_metrics].round(3)
    return summary.reset_index(drop=True)


def extract_year_from_filename(filename: str) -> int:
    """Extrai um único ano de quatro dígitos do nome do arquivo."""
    years = {
        int(match)
        for match in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", Path(filename).stem)
    }
    if not years:
        raise WorkbookError(
            "o nome não contém um ano de quatro dígitos, como 2026"
        )
    if len(years) > 1:
        raise WorkbookError(
            "o nome contém mais de um ano; mantenha somente o ano dos dados"
        )
    return years.pop()


def process_uploads(files: Sequence[tuple[str, bytes]]) -> ProcessingResult:
    """Processa vários arquivos e consolida as médias mensais do SIN."""
    return _process_sources(files, _load_single_workbook)


def process_parquet_files(
    files: Sequence[tuple[str, Path]],
) -> ProcessingResult:
    """Processa arquivos Parquet anuais já baixados do portal do ONS."""
    return _process_sources(files, _load_single_parquet)


def _process_sources(
    files: Sequence[tuple[str, Any]],
    loader: Callable[
        [str, Any, int],
        tuple[pd.DataFrame, dict[str, object], list[str]],
    ],
) -> ProcessingResult:
    frames: list[pd.DataFrame] = []
    reports: list[dict[str, object]] = []
    warnings: list[str] = []
    errors: list[str] = []

    for file_order, (filename, content) in enumerate(files):
        try:
            frame, report, file_warnings = loader(filename, content, file_order)
            frames.append(frame)
            reports.append(report)
            warnings.extend(file_warnings)
        except Exception as exc:
            errors.append(f"{filename}: {exc}")

    if not frames:
        return ProcessingResult(
            monthly=pd.DataFrame(),
            file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
            warnings=warnings,
            errors=errors,
            metric_columns=[],
            hourly_rows=0,
        )

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["din_instante", "__subsystem_key", "__file_order"], kind="stable"
    ).reset_index(drop=True)

    overlap_mask = combined.duplicated(
        subset=["__subsystem_key", "din_instante"],
        keep="last",
    )
    overlap_count = int(overlap_mask.sum())
    if overlap_count:
        combined = combined.loc[~overlap_mask].copy()
        warnings.append(
            f"{overlap_count:,} registro(s) sobreposto(s) entre arquivos foram "
            "removidos; para cada horário foi mantido o último arquivo carregado."
        )

    metric_columns = _ordered_metrics(
        [
            column
            for column in combined.columns
            if column.startswith("val_") and combined[column].notna().any()
        ]
    )
    if not metric_columns:
        errors.append("Nenhuma coluna numérica de balanço pôde ser consolidada.")
        return ProcessingResult(
            monthly=pd.DataFrame(),
            file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
            warnings=warnings,
            errors=errors,
            metric_columns=[],
            hourly_rows=len(combined),
        )

    sin_combined = combined.loc[_sin_mask(combined)].copy()
    monthly = (
        _monthly_summary(sin_combined, metric_columns)
        if not sin_combined.empty
        else pd.DataFrame()
    )
    display_metric_columns = [_metric_label(column) for column in metric_columns]
    subsystem_columns = [
        column
        for column in [
            "id_subsistema",
            "nom_subsistema",
            "__subsystem_key",
            "__subsystem_label",
        ]
        if column in combined.columns
    ]
    hourly = combined[[*subsystem_columns, "din_instante", *metric_columns]].copy()
    hourly = hourly.sort_values(
        ["din_instante", "__subsystem_key"], kind="stable"
    ).reset_index(drop=True)

    return ProcessingResult(
        monthly=monthly,
        file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
        warnings=warnings,
        errors=errors,
        metric_columns=display_metric_columns,
        hourly_rows=len(combined),
        hourly=hourly,
    )


def _load_single_workbook(
    filename: str,
    content: bytes,
    file_order: int,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    year = extract_year_from_filename(filename)
    suffix = Path(filename).suffix.lower()
    engine = "xlrd" if suffix == ".xls" else "openpyxl"

    try:
        workbook = pd.read_excel(
            BytesIO(content),
            sheet_name=None,
            engine=engine,
        )
    except Exception as exc:
        raise WorkbookError(f"não foi possível abrir o Excel ({exc})") from exc

    eligible_sheets: list[pd.DataFrame] = []
    for sheet_name, raw in workbook.items():
        prepared = _prepare_sheet(raw)
        if prepared is not None:
            prepared["__sheet"] = sheet_name
            eligible_sheets.append(prepared)

    if not eligible_sheets:
        raise WorkbookError(
            "nenhuma planilha contém data, identificação do subsistema e "
            "colunas de valores iniciadas por 'val_'"
        )

    data = pd.concat(eligible_sheets, ignore_index=True, sort=False)
    return _validate_source_data(
        filename=filename,
        data=data,
        year=year,
        file_order=file_order,
    )


def _load_single_parquet(
    filename: str,
    path: Path,
    file_order: int,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    year = extract_year_from_filename(filename)
    try:
        raw = pd.read_parquet(path, engine="pyarrow")
    except Exception as exc:
        raise WorkbookError(f"não foi possível abrir o Parquet ({exc})") from exc

    data = _prepare_sheet(raw)
    if data is None:
        raise WorkbookError(
            "o Parquet não contém data, identificação do subsistema e "
            "colunas de valores iniciadas por 'val_'"
        )
    return _validate_source_data(
        filename=filename,
        data=data,
        year=year,
        file_order=file_order,
    )


def _validate_source_data(
    filename: str,
    data: pd.DataFrame,
    year: int,
    file_order: int,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    prepared = _add_subsystem_metadata(data)
    prepared = prepared.loc[prepared["__subsystem_key"].ne("")].copy()
    if prepared.empty:
        raise WorkbookError("não foram encontrados subsistemas identificáveis")

    file_warnings: list[str] = []
    prepared["din_instante"] = _parse_datetime_series(prepared["din_instante"])
    invalid_dates = int(prepared["din_instante"].isna().sum())
    if invalid_dates:
        file_warnings.append(
            f"{filename}: {invalid_dates:,} linha(s) com data inválida "
            "foram ignoradas."
        )
        prepared = prepared.dropna(subset=["din_instante"])

    internal_years = sorted(
        int(value) for value in prepared["din_instante"].dt.year.dropna().unique()
    )
    data_for_year = prepared.loc[prepared["din_instante"].dt.year.eq(year)].copy()
    if data_for_year.empty:
        found = ", ".join(map(str, internal_years)) or "nenhum"
        raise WorkbookError(
            f"o nome indica {year}, mas as datas internas contêm: {found}"
        )

    other_years = [value for value in internal_years if value != year]
    if other_years:
        file_warnings.append(
            f"{filename}: o nome indica {year}; linhas dos anos "
            f"{', '.join(map(str, other_years))} foram ignoradas."
        )

    metric_columns = [
        column for column in data_for_year.columns if column.startswith("val_")
    ]
    for column in metric_columns:
        data_for_year[column] = _parse_numeric_series(data_for_year[column])

    no_values_mask = data_for_year[metric_columns].isna().all(axis=1)
    no_values_count = int(no_values_mask.sum())
    if no_values_count:
        file_warnings.append(
            f"{filename}: {no_values_count:,} linha(s) sem nenhum valor "
            "numérico foram ignoradas."
        )
        data_for_year = data_for_year.loc[~no_values_mask].copy()

    if data_for_year.empty:
        raise WorkbookError("não restaram linhas válidas após a validação")

    duplicate_mask = data_for_year.duplicated(
        subset=["__subsystem_key", "din_instante"], keep="last"
    )
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        data_for_year = data_for_year.loc[~duplicate_mask].copy()
        file_warnings.append(
            f"{filename}: {duplicate_count:,} horário(s) duplicado(s) foram "
            "removidos."
        )

    data_for_year["__ano_arquivo"] = year
    data_for_year["__arquivo"] = filename
    data_for_year["__file_order"] = file_order
    data_for_year = data_for_year.sort_values(
        ["din_instante", "__subsystem_key"], kind="stable"
    )

    sin_for_year = data_for_year.loc[_sin_mask(data_for_year)].copy()
    report_data = sin_for_year if not sin_for_year.empty else data_for_year
    start = report_data["din_instante"].min()
    end = report_data["din_instante"].max()
    report = {
        "Arquivo": filename,
        "Ano": year,
        "Período lido": f"{start:%d/%m/%Y} a {end:%d/%m/%Y}",
        "Linhas horárias do SIN": len(sin_for_year),
        "Meses": int(report_data["din_instante"].dt.month.nunique()),
        "Duplicatas removidas": duplicate_count,
        "Situação": "Processado",
    }
    return data_for_year, report, file_warnings


def _add_subsystem_metadata(data: pd.DataFrame) -> pd.DataFrame:
    prepared = data.copy()
    if "id_subsistema" not in prepared.columns:
        prepared["id_subsistema"] = ""
    if "nom_subsistema" not in prepared.columns:
        prepared["nom_subsistema"] = ""

    ids = prepared["id_subsistema"].fillna("").map(_clean_subsystem_text)
    names = prepared["nom_subsistema"].fillna("").map(_clean_subsystem_text)
    keys = ids.map(str.upper).where(
        ids.ne(""), names.map(_subsystem_key_from_name)
    )
    sin_rows = _sin_mask(prepared)
    keys = keys.mask(sin_rows, "SIN")

    prepared["id_subsistema"] = ids
    prepared["nom_subsistema"] = names
    prepared["__subsystem_key"] = keys
    prepared["__subsystem_label"] = [
        _subsystem_label(key, subsystem_id, name)
        for key, subsystem_id, name in zip(keys, ids, names)
    ]
    return prepared


def _clean_subsystem_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _subsystem_key_from_name(name: str) -> str:
    normalized = _normalize_name(name)
    if normalized in {"sin", "sistema_interligado_nacional"}:
        return "SIN"
    return normalized.upper()


def _subsystem_label(key: str, subsystem_id: str, name: str) -> str:
    if key == "SIN":
        return "SIN"
    display_id = subsystem_id.upper() if subsystem_id else key
    display_name = name.title() if name else ""
    if display_name and _normalize_name(display_name) != _normalize_name(display_id):
        return f"{display_id} · {display_name}"
    return display_id


def _prepare_sheet(raw: pd.DataFrame) -> pd.DataFrame | None:
    if raw.empty:
        return None

    data = raw.dropna(how="all").copy()
    normalized_columns = [_normalize_name(column) for column in data.columns]
    data.columns = normalized_columns
    data = data.loc[:, ~data.columns.duplicated()].copy()

    alias_lookup = {
        alias: canonical
        for canonical, aliases in COLUMN_ALIASES.items()
        for alias in aliases
    }
    data = data.rename(
        columns={
            column: alias_lookup.get(column, column)
            for column in data.columns
        }
    )

    has_subsystem = (
        "id_subsistema" in data.columns or "nom_subsistema" in data.columns
    )
    metric_columns = [
        column for column in data.columns if column.startswith("val_")
    ]
    if "din_instante" not in data.columns or not has_subsystem or not metric_columns:
        return None

    selected = [
        column
        for column in ["id_subsistema", "nom_subsistema", "din_instante"]
        if column in data.columns
    ]
    selected.extend(metric_columns)
    return data[selected]


def _sin_mask(data: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=data.index)
    if "id_subsistema" in data.columns:
        ids = data["id_subsistema"].fillna("").map(_normalize_name)
        mask = mask | ids.isin({"sin", "sistema_interligado_nacional"})
    if "nom_subsistema" in data.columns:
        names = data["nom_subsistema"].fillna("").map(_normalize_name)
        mask = mask | names.str.contains(
            r"(?:^|_)sistema_interligado_nacional(?:_|$)", regex=True
        )
    return mask


def _parse_datetime_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    numeric = pd.to_numeric(series, errors="coerce")
    likely_excel_serial = (
        numeric.notna().mean() >= 0.8
        and not numeric.dropna().empty
        and 20_000 <= float(numeric.dropna().median()) <= 80_000
    )
    if likely_excel_serial:
        return pd.to_datetime(
            numeric,
            unit="D",
            origin="1899-12-30",
            errors="coerce",
        )
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def _parse_numeric_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_numeric(series, errors="coerce")
    missing = parsed.isna() & series.notna()
    if not missing.any():
        return parsed

    fallback = series.loc[missing].map(_parse_numeric_token)
    parsed.loc[missing] = pd.to_numeric(fallback, errors="coerce")
    return parsed


def _parse_numeric_token(value: object) -> object:
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")
    if "," in text:
        return text.replace(",", ".")
    return text


def _monthly_summary(
    combined: pd.DataFrame,
    metric_columns: list[str],
) -> pd.DataFrame:
    data = combined.copy()
    data["Ano"] = data["din_instante"].dt.year.astype(int)
    data["Mês nº"] = data["din_instante"].dt.month.astype(int)

    grouped = data.groupby(["Ano", "Mês nº"], sort=True, observed=True)
    means = grouped[metric_columns].mean()
    hours = grouped["din_instante"].nunique().rename("Horas com dados")

    monthly = means.join(hours).reset_index()
    monthly["Mês"] = monthly["Mês nº"].map(MONTH_NAMES)
    monthly["Período"] = (
        monthly["Ano"].astype(str)
        + "-"
        + monthly["Mês nº"].astype(str).str.zfill(2)
    )
    monthly["Horas esperadas"] = monthly.apply(
        lambda row: calendar.monthrange(
            int(row["Ano"]), int(row["Mês nº"])
        )[1]
        * 24,
        axis=1,
    )
    monthly["Cobertura (%)"] = (
        monthly["Horas com dados"] / monthly["Horas esperadas"] * 100
    ).round(1)
    monthly["Status do mês"] = monthly.apply(_month_status, axis=1)

    monthly = monthly.rename(
        columns={column: _metric_label(column) for column in metric_columns}
    )
    display_metrics = [_metric_label(column) for column in metric_columns]
    ordered_columns = [
        "Ano",
        "Mês nº",
        "Mês",
        "Período",
        "Horas com dados",
        "Horas esperadas",
        "Cobertura (%)",
        "Status do mês",
        *display_metrics,
    ]
    monthly = monthly[ordered_columns].sort_values(
        ["Ano", "Mês nº"], kind="stable"
    )
    monthly[display_metrics] = monthly[display_metrics].round(3)
    return monthly.reset_index(drop=True)


def _month_status(row: pd.Series) -> str:
    actual = int(row["Horas com dados"])
    expected = int(row["Horas esperadas"])
    return _coverage_status(actual, expected)


def _coverage_status(actual: int, expected: int) -> str:
    if actual == expected:
        return "Completo"
    if actual < expected:
        return "Parcial"
    return "Revisar"


def _expected_hours(
    timestamp: pd.Timestamp,
    granularity: Granularity,
) -> int:
    if granularity == "hourly":
        return 1
    if granularity == "daily":
        return 24
    if granularity == "monthly":
        return calendar.monthrange(timestamp.year, timestamp.month)[1] * 24
    return (366 if calendar.isleap(timestamp.year) else 365) * 24


def _timestamp_boundary(
    series: pd.Series,
    value: date | pd.Timestamp,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    timezone = series.dt.tz
    if timezone is not None and timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone)
    return timestamp


def _ordered_metrics(columns: list[str]) -> list[str]:
    unique = set(columns)
    known = [column for column in METRIC_LABELS if column in unique]
    extras = sorted(unique.difference(METRIC_LABELS))
    return known + extras


def _metric_label(column: str) -> str:
    if column in METRIC_LABELS:
        return METRIC_LABELS[column]
    readable = column.removeprefix("val_").replace("_", " ").strip().capitalize()
    return f"{readable} (média)"


def _normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")
