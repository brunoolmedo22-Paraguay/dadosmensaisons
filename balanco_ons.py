from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Sequence

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


def build_csv_export(data: pd.DataFrame) -> pd.DataFrame:
    """Retorna somente as colunas finais solicitadas para o CSV."""
    export = data.copy()
    for column in CSV_EXPORT_COLUMNS:
        if column not in export.columns:
            export[column] = pd.NA
    return export[CSV_EXPORT_COLUMNS]


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
    frames: list[pd.DataFrame] = []
    reports: list[dict[str, object]] = []
    warnings: list[str] = []
    errors: list[str] = []

    for file_order, (filename, content) in enumerate(files):
        try:
            frame, report, file_warnings = _load_single_workbook(
                filename=filename,
                content=content,
                file_order=file_order,
            )
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
        ["din_instante", "__file_order"], kind="stable"
    ).reset_index(drop=True)

    overlap_mask = combined.duplicated(subset=["din_instante"], keep="last")
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

    monthly = _monthly_summary(combined, metric_columns)
    display_metric_columns = [_metric_label(column) for column in metric_columns]

    return ProcessingResult(
        monthly=monthly,
        file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
        warnings=warnings,
        errors=errors,
        metric_columns=display_metric_columns,
        hourly_rows=len(combined),
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
    sin_mask = _sin_mask(data)
    sin = data.loc[sin_mask].copy()
    if sin.empty:
        raise WorkbookError(
            "não foram encontradas linhas do SIN (id_subsistema = 'SIN')"
        )

    file_warnings: list[str] = []
    sin["din_instante"] = _parse_datetime_series(sin["din_instante"])
    invalid_dates = int(sin["din_instante"].isna().sum())
    if invalid_dates:
        file_warnings.append(
            f"{filename}: {invalid_dates:,} linha(s) do SIN com data inválida "
            "foram ignoradas."
        )
        sin = sin.dropna(subset=["din_instante"])

    internal_years = sorted(
        int(value) for value in sin["din_instante"].dt.year.dropna().unique()
    )
    sin_for_year = sin.loc[sin["din_instante"].dt.year.eq(year)].copy()
    if sin_for_year.empty:
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
        column for column in sin_for_year.columns if column.startswith("val_")
    ]
    for column in metric_columns:
        sin_for_year[column] = _parse_numeric_series(sin_for_year[column])

    no_values_mask = sin_for_year[metric_columns].isna().all(axis=1)
    no_values_count = int(no_values_mask.sum())
    if no_values_count:
        file_warnings.append(
            f"{filename}: {no_values_count:,} linha(s) sem nenhum valor "
            "numérico foram ignoradas."
        )
        sin_for_year = sin_for_year.loc[~no_values_mask].copy()

    if sin_for_year.empty:
        raise WorkbookError("não restaram linhas válidas após a validação")

    duplicate_mask = sin_for_year.duplicated(
        subset=["din_instante"], keep="last"
    )
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        sin_for_year = sin_for_year.loc[~duplicate_mask].copy()
        file_warnings.append(
            f"{filename}: {duplicate_count:,} horário(s) duplicado(s) foram "
            "removidos."
        )

    sin_for_year["__ano_arquivo"] = year
    sin_for_year["__arquivo"] = filename
    sin_for_year["__file_order"] = file_order
    sin_for_year = sin_for_year.sort_values("din_instante", kind="stable")

    start = sin_for_year["din_instante"].min()
    end = sin_for_year["din_instante"].max()
    report = {
        "Arquivo": filename,
        "Ano": year,
        "Período lido": f"{start:%d/%m/%Y} a {end:%d/%m/%Y}",
        "Linhas horárias do SIN": len(sin_for_year),
        "Meses": int(sin_for_year["din_instante"].dt.month.nunique()),
        "Duplicatas removidas": duplicate_count,
        "Situação": "Processado",
    }
    return sin_for_year, report, file_warnings


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
    if actual == expected:
        return "Completo"
    if actual < expected:
        return "Parcial"
    return "Revisar"


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
