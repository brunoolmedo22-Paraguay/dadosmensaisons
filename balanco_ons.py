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

SUBSYSTEM_LABELS = {
    "SIN": "Sistema Interligado Nacional (SIN)",
    "SE": "Sudeste/Centro-Oeste (SE/CO)",
    "S": "Sul (S)",
    "NE": "Nordeste (NE)",
    "N": "Norte (N)",
}

SUBSYSTEM_ALIASES = {
    "sin": "SIN",
    "sistema_interligado_nacional": "SIN",
    "se": "SE",
    "se_co": "SE",
    "seco": "SE",
    "sudeste": "SE",
    "sudeste_centro_oeste": "SE",
    "sudeste_centrooeste": "SE",
    "s": "S",
    "sul": "S",
    "ne": "NE",
    "nordeste": "NE",
    "n": "N",
    "norte": "N",
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
    "Registros horários",
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
    subsystem_options: list[str] = field(default_factory=list)


def build_csv_export(data: pd.DataFrame) -> pd.DataFrame:
    """Retorna somente as colunas finais solicitadas para o CSV."""
    export = data.copy()
    for column in CSV_EXPORT_COLUMNS:
        if column not in export.columns:
            export[column] = pd.NA
    return export[CSV_EXPORT_COLUMNS]


def build_granular_csv_export(
    data: pd.DataFrame,
    granularity: Granularity,
    metric_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Monta o CSV correspondente à discretização exibida."""
    if granularity not in GRANULARITY_PERIOD_COLUMNS:
        raise ValueError(f"Discretização inválida: {granularity}")

    export = data.copy()
    period_columns = GRANULARITY_PERIOD_COLUMNS[granularity]
    if metric_columns is None:
        known_metrics = list(METRIC_LABELS.values())
        extra_metrics = [
            column
            for column in export.columns
            if column.endswith(" (média)") and column not in known_metrics
        ]
        export_metrics = [*known_metrics, *extra_metrics]
    else:
        export_metrics = list(dict.fromkeys(metric_columns))

    for column in [*period_columns, *export_metrics]:
        if column not in export.columns:
            export[column] = pd.NA

    if "Data e hora" in export.columns:
        timestamps = pd.to_datetime(export["Data e hora"], errors="coerce")
        export["Data e hora"] = timestamps.dt.strftime("%d/%m/%Y %H:%M")
    if "Data" in export.columns:
        dates = pd.to_datetime(export["Data"], errors="coerce")
        export["Data"] = dates.dt.strftime("%d/%m/%Y")

    return export[[*period_columns, *export_metrics]]


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
    """Processa vários arquivos e preserva as séries de cada subsistema."""
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
        ["Subsistema", "din_instante", "__file_order"],
        kind="stable",
    ).reset_index(drop=True)

    overlap_mask = combined.duplicated(
        subset=["Subsistema", "din_instante"],
        keep="last",
    )
    overlap_count = int(overlap_mask.sum())
    if overlap_count:
        combined = combined.loc[~overlap_mask].copy()
        warnings.append(
            f"{overlap_count:,} registro(s) de subsistema sobreposto(s) entre "
            "arquivos foram removidos; para cada subsistema e horário foi "
            "mantido o último arquivo carregado."
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

    default_subsystem = SUBSYSTEM_LABELS["SIN"]
    default_data = combined.loc[
        combined["Subsistema"].eq(default_subsystem)
    ].copy()
    if default_data.empty:
        default_subsystem = str(combined["Subsistema"].iloc[0])
        default_data = combined.loc[
            combined["Subsistema"].eq(default_subsystem)
        ].copy()

    monthly = _monthly_summary(default_data, metric_columns)
    display_metric_columns = [_metric_label(column) for column in metric_columns]
    hourly = combined[["Subsistema", "din_instante", *metric_columns]].copy()
    hourly = hourly.sort_values(
        ["Subsistema", "din_instante"],
        kind="stable",
    ).reset_index(drop=True)
    available_subsystems = set(hourly["Subsistema"].dropna().astype(str))
    subsystem_options = [
        label
        for label in SUBSYSTEM_LABELS.values()
        if label in available_subsystems
    ]
    subsystem_options.extend(sorted(available_subsystems.difference(subsystem_options)))

    return ProcessingResult(
        monthly=monthly,
        file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
        warnings=warnings,
        errors=errors,
        metric_columns=display_metric_columns,
        hourly_rows=len(combined),
        hourly=hourly,
        subsystem_options=subsystem_options,
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
    subsystem_labels = _subsystem_labels(data)
    validated = data.loc[subsystem_labels.notna()].copy()
    validated["Subsistema"] = subsystem_labels.loc[
        subsystem_labels.notna()
    ].astype(str)
    if validated.empty:
        raise WorkbookError(
            "não foram encontradas linhas dos subsistemas esperados "
            "(SIN, SE/CO, Sul, Nordeste ou Norte)"
        )

    file_warnings: list[str] = []
    validated["din_instante"] = _parse_datetime_series(
        validated["din_instante"]
    )
    invalid_dates = int(validated["din_instante"].isna().sum())
    if invalid_dates:
        file_warnings.append(
            f"{filename}: {invalid_dates:,} linha(s) de subsistema com data "
            "inválida foram ignoradas."
        )
        validated = validated.dropna(subset=["din_instante"])

    internal_years = sorted(
        int(value)
        for value in validated["din_instante"].dt.year.dropna().unique()
    )
    data_for_year = validated.loc[
        validated["din_instante"].dt.year.eq(year)
    ].copy()
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
        subset=["Subsistema", "din_instante"],
        keep="last",
    )
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        data_for_year = data_for_year.loc[~duplicate_mask].copy()
        file_warnings.append(
            f"{filename}: {duplicate_count:,} registro(s) duplicado(s) de "
            "subsistema e horário foram removidos."
        )

    data_for_year["__ano_arquivo"] = year
    data_for_year["__arquivo"] = filename
    data_for_year["__file_order"] = file_order
    data_for_year = data_for_year.sort_values(
        ["Subsistema", "din_instante"],
        kind="stable",
    )

    start = data_for_year["din_instante"].min()
    end = data_for_year["din_instante"].max()
    report = {
        "Arquivo": filename,
        "Ano": year,
        "Período lido": f"{start:%d/%m/%Y} a {end:%d/%m/%Y}",
        "Registros horários": len(data_for_year),
        "Meses": int(data_for_year["din_instante"].dt.month.nunique()),
        "Duplicatas removidas": duplicate_count,
        "Situação": "Processado",
    }
    return data_for_year, report, file_warnings


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


def _subsystem_labels(data: pd.DataFrame) -> pd.Series:
    labels = pd.Series(pd.NA, index=data.index, dtype="object")
    for column in ("id_subsistema", "nom_subsistema"):
        if column not in data.columns:
            continue
        normalized = data[column].fillna("").map(_normalize_name)
        codes = normalized.map(SUBSYSTEM_ALIASES)
        sin_name_mask = normalized.str.contains(
            r"(?:^|_)sistema_interligado_nacional(?:_|$)",
            regex=True,
        )
        codes = codes.mask(codes.isna() & sin_name_mask, "SIN")
        labels = labels.fillna(codes.map(SUBSYSTEM_LABELS))
    return labels


def _sin_mask(data: pd.DataFrame) -> pd.Series:
    return _subsystem_labels(data).eq(SUBSYSTEM_LABELS["SIN"])


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
