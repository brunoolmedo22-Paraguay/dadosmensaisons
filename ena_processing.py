from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
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

# Os nomes técnicos seguem os códigos publicados pelo ONS. Embora uma versão
# antiga do dicionário descreva "MWmês", as colunas oficiais usam o sufixo
# ``mwmed``, que é também a convenção operacional da série diária de ENA.
METRIC_LABELS = {
    "ena_bruta_regiao_mwmed": "ENA bruta (MWmed)",
    "ena_bruta_regiao_percentualmlt": "ENA bruta (% MLT)",
    "ena_armazenavel_regiao_mwmed": "ENA armazenável (MWmed)",
    "ena_armazenavel_regiao_percentualmlt": "ENA armazenável (% MLT)",
}

Granularity = Literal["daily", "monthly", "yearly"]
GRANULARITY_PERIOD_COLUMNS: dict[Granularity, list[str]] = {
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
    "ena_data": {
        "ena_data",
        "data",
        "data_referencia",
        "dia_observado",
    },
    "ena_bruta_regiao_mwmed": {
        "ena_bruta_regiao_mwmed",
        "ena_bruta_subsistema_mwmed",
        "ena_bruta_mwmed",
    },
    "ena_bruta_regiao_percentualmlt": {
        "ena_bruta_regiao_percentualmlt",
        "ena_bruta_subsistema_percentualmlt",
        "ena_bruta_percentualmlt",
        "ena_bruta_percentual_mlt",
    },
    "ena_armazenavel_regiao_mwmed": {
        "ena_armazenavel_regiao_mwmed",
        "ena_armazenavel_subsistema_mwmed",
        "ena_armazenavel_mwmed",
    },
    "ena_armazenavel_regiao_percentualmlt": {
        "ena_armazenavel_regiao_percentualmlt",
        "ena_armazenavel_subsistema_percentualmlt",
        "ena_armazenavel_percentualmlt",
        "ena_armazenavel_percentual_mlt",
    },
}

REPORT_COLUMNS = [
    "Arquivo",
    "Ano",
    "Período lido",
    "Linhas diárias",
    "Subsistemas",
    "Duplicatas removidas",
    "Situação",
]

SUBSYSTEM_ORDER = {"SIN": 0, "SE": 1, "S": 2, "NE": 3, "N": 4}
REQUIRED_SIN_SUBSYSTEMS = frozenset({"SE", "S", "NE", "N"})
SUBSYSTEM_FALLBACK_LABELS = {
    "SIN": "SIN",
    "SE": "Sudeste/Centro-Oeste",
    "S": "Sul",
    "NE": "Nordeste",
    "N": "Norte",
}


class WorkbookError(ValueError):
    """Erro legível para um arquivo que não segue o formato esperado."""


@dataclass
class ProcessingResult:
    file_report: pd.DataFrame
    warnings: list[str]
    errors: list[str]
    metric_columns: list[str]
    daily_rows: int
    daily: pd.DataFrame = field(default_factory=pd.DataFrame)


def available_subsystems(daily: pd.DataFrame) -> list[tuple[str, str]]:
    """Lista subsistemas disponíveis como pares ``(chave, rótulo)``."""
    if daily.empty or "__subsystem_key" not in daily.columns:
        return []

    labels_by_key: dict[str, str] = {}
    columns = ["__subsystem_key", "__subsystem_label"]
    for key, label in daily[columns].drop_duplicates().itertuples(index=False):
        key_text = str(key).strip()
        if not key_text:
            continue
        label_text = str(label).strip() if pd.notna(label) else ""
        labels_by_key[key_text] = (
            label_text or SUBSYSTEM_FALLBACK_LABELS.get(key_text, key_text)
        )

    return sorted(
        labels_by_key.items(),
        key=lambda item: (
            SUBSYSTEM_ORDER.get(item[0], 99),
            item[1].casefold(),
        ),
    )


def filter_daily_by_subsystem(
    daily: pd.DataFrame,
    subsystem_key: str,
) -> pd.DataFrame:
    """Filtra a série diária por subsistema."""
    if daily.empty or "__subsystem_key" not in daily.columns:
        return daily.iloc[0:0].copy()
    return daily.loc[daily["__subsystem_key"].eq(subsystem_key)].copy()


def build_granular_csv_export(
    data: pd.DataFrame,
    granularity: Granularity,
) -> pd.DataFrame:
    """Monta o CSV correspondente à discretização exibida."""
    if granularity not in GRANULARITY_PERIOD_COLUMNS:
        raise ValueError(f"Discretização inválida: {granularity}")

    export = data.copy()
    period_columns = GRANULARITY_PERIOD_COLUMNS[granularity]
    metric_columns = list(METRIC_LABELS.values())
    for column in [*period_columns, *metric_columns]:
        if column not in export.columns:
            export[column] = pd.NA

    if "Data" in export.columns:
        dates = pd.to_datetime(export["Data"], errors="coerce")
        export["Data"] = dates.dt.strftime("%d/%m/%Y")

    return export[[*period_columns, *metric_columns]]


def build_period_summary(
    daily: pd.DataFrame,
    granularity: Granularity,
    start_date: date | pd.Timestamp | None = None,
    end_date: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Agrega a série diária de ENA em base diária, mensal ou anual."""
    if granularity not in GRANULARITY_PERIOD_COLUMNS:
        raise ValueError(f"Discretização inválida: {granularity}")
    if daily.empty or "ena_data" not in daily.columns:
        return pd.DataFrame()

    data = daily.copy()
    data["ena_data"] = pd.to_datetime(data["ena_data"], errors="coerce")
    data = data.dropna(subset=["ena_data"])
    if start_date is not None:
        data = data.loc[data["ena_data"].ge(pd.Timestamp(start_date))]
    if end_date is not None:
        data = data.loc[data["ena_data"].lt(pd.Timestamp(end_date) + pd.Timedelta(days=1))]
    if data.empty:
        return pd.DataFrame()

    metric_codes = [
        code for code in METRIC_LABELS if code in data.columns and data[code].notna().any()
    ]
    if not metric_codes:
        return pd.DataFrame()

    if granularity == "daily":
        data["__period_start"] = data["ena_data"].dt.floor("D")
    elif granularity == "monthly":
        data["__period_start"] = data["ena_data"].dt.to_period("M").dt.to_timestamp()
    else:
        data["__period_start"] = data["ena_data"].dt.to_period("Y").dt.to_timestamp()

    grouped = data.groupby("__period_start", sort=True, observed=True)
    means = grouped[metric_codes].mean()
    days = grouped["ena_data"].nunique().rename("Dias com dados")
    summary = means.join(days).reset_index()
    summary["Dias esperados"] = summary["__period_start"].map(
        lambda timestamp: _expected_days(pd.Timestamp(timestamp), granularity)
    )
    summary["Cobertura (%)"] = (
        summary["Dias com dados"] / summary["Dias esperados"] * 100
    ).round(1)
    summary["Status do período"] = summary.apply(
        lambda row: "Completo"
        if int(row["Dias com dados"]) >= int(row["Dias esperados"])
        else "Parcial",
        axis=1,
    )

    if granularity == "daily":
        summary["Data"] = summary["__period_start"].dt.date
    elif granularity == "monthly":
        summary["Ano"] = summary["__period_start"].dt.year.astype(int)
        summary["Mês nº"] = summary["__period_start"].dt.month.astype(int)
        summary["Mês"] = summary["Mês nº"].map(MONTH_NAMES)
    else:
        summary["Ano"] = summary["__period_start"].dt.year.astype(int)

    summary = summary.rename(columns=METRIC_LABELS)
    display_metrics = [METRIC_LABELS[code] for code in metric_codes]
    internal_columns = ["__period_start"]
    if granularity == "monthly":
        internal_columns.append("Mês nº")
    ordered_columns = [
        *GRANULARITY_PERIOD_COLUMNS[granularity],
        *internal_columns,
        "Dias com dados",
        "Dias esperados",
        "Cobertura (%)",
        "Status do período",
        *display_metrics,
    ]
    summary = summary[ordered_columns].sort_values("__period_start", kind="stable")
    summary[display_metrics] = summary[display_metrics].round(3)
    return summary.reset_index(drop=True)


def extract_year_from_filename(filename: str) -> int:
    years = {
        int(match)
        for match in re.findall(
            r"(?<!\d)((?:19|20)\d{2})(?!\d)", Path(filename).stem
        )
    }
    if not years:
        raise WorkbookError("o nome não contém um ano de quatro dígitos, como 2026")
    if len(years) > 1:
        raise WorkbookError("o nome contém mais de um ano")
    return years.pop()


def process_data_files(
    files: Sequence[tuple[str, Path]],
) -> ProcessingResult:
    """Processa uma lista mista de arquivos anuais CSV e Parquet de ENA."""
    return _process_sources(files, _load_single_source)


def process_parquet_files(
    files: Sequence[tuple[str, Path]],
) -> ProcessingResult:
    """Compatibilidade: aceita também CSVs usados como fallback histórico."""
    return process_data_files(files)


def _process_sources(
    files: Sequence[tuple[str, Any]],
    loader: Callable[[str, Any, int], tuple[pd.DataFrame, dict[str, object], list[str]]],
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
            file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
            warnings=warnings,
            errors=errors,
            metric_columns=list(METRIC_LABELS.values()),
            daily_rows=0,
        )

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["ena_data", "__subsystem_key", "__file_order"], kind="stable"
    ).reset_index(drop=True)

    overlap_mask = combined.duplicated(
        subset=["__subsystem_key", "ena_data"], keep="last"
    )
    overlap_count = int(overlap_mask.sum())
    if overlap_count:
        combined = combined.loc[~overlap_mask].copy()
        warnings.append(
            f"Foram removidos {overlap_count} registro(s) repetido(s) entre arquivos anuais."
        )

    combined = _append_sin_series(combined)
    combined = combined.sort_values(
        ["ena_data", "__subsystem_key"], kind="stable"
    ).reset_index(drop=True)

    return ProcessingResult(
        daily=combined,
        file_report=pd.DataFrame(reports, columns=REPORT_COLUMNS),
        warnings=warnings,
        errors=errors,
        metric_columns=list(METRIC_LABELS.values()),
        daily_rows=len(combined),
    )


def _load_single_source(
    filename: str,
    path: Path,
    file_order: int,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".parquet":
        return _load_single_parquet(filename, path, file_order)
    if suffix == ".csv":
        return _load_single_csv(filename, path, file_order)
    raise WorkbookError("formato não suportado; use CSV ou Parquet")


def _load_single_parquet(
    filename: str,
    path: Path,
    file_order: int,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    try:
        raw = pd.read_parquet(path)
    except Exception as exc:
        raise WorkbookError(f"não foi possível ler o Parquet: {exc}") from exc
    return _normalize_loaded_frame(filename, raw, file_order, "Parquet")


def _load_single_csv(
    filename: str,
    path: Path,
    file_order: int,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    read_errors: list[str] = []
    raw: pd.DataFrame | None = None
    for separator in (";", ","):
        try:
            candidate = pd.read_csv(
                path,
                sep=separator,
                encoding="utf-8-sig",
                dtype="string",
                low_memory=False,
            )
        except Exception as exc:
            read_errors.append(str(exc))
            continue
        if len(candidate.columns) > 1:
            raw = candidate
            break
    if raw is None:
        detail = read_errors[-1] if read_errors else "delimitador não reconhecido"
        raise WorkbookError(f"não foi possível ler o CSV: {detail}")
    return _normalize_loaded_frame(filename, raw, file_order, "CSV")


def _normalize_loaded_frame(
    filename: str,
    raw: pd.DataFrame,
    file_order: int,
    source_format: str,
) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    year = extract_year_from_filename(filename)
    if raw.empty:
        raise WorkbookError("o arquivo está vazio")

    frame = raw.copy()
    frame.columns = [_normalize_column_name(column) for column in frame.columns]
    frame = _rename_aliases(frame)
    required = [
        "id_subsistema",
        "nom_subsistema",
        "ena_data",
        *METRIC_LABELS.keys(),
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise WorkbookError("colunas obrigatórias ausentes: " + ", ".join(missing))

    warnings: list[str] = []
    # Os CSVs históricos do ONS usam ISO (AAAA-MM-DD), enquanto arquivos
    # alternativos/testes podem usar DD/MM/AAAA. ``format="mixed"`` evita que
    # ``dayfirst=True`` interprete uma data ISO como ano-dia-mês e descarte
    # todos os dias posteriores ao dia 12.
    frame["ena_data"] = pd.to_datetime(
        frame["ena_data"],
        errors="coerce",
        format="mixed",
        dayfirst=True,
    ).dt.floor("D")
    invalid_dates = int(frame["ena_data"].isna().sum())
    if invalid_dates:
        warnings.append(f"{filename}: {invalid_dates} linha(s) com data inválida foram removidas.")

    frame["__subsystem_key"] = frame["id_subsistema"].map(_normalize_subsystem_key)
    frame["__subsystem_label"] = [
        _normalize_subsystem_label(key, label)
        for key, label in zip(frame["__subsystem_key"], frame["nom_subsistema"])
    ]
    for metric in METRIC_LABELS:
        frame[metric] = _to_numeric(frame[metric])

    frame = frame.dropna(subset=["ena_data", "__subsystem_key", *METRIC_LABELS.keys()])
    outside_year = frame["ena_data"].dt.year.ne(year)
    outside_count = int(outside_year.sum())
    if outside_count:
        warnings.append(
            f"{filename}: {outside_count} linha(s) fora de {year} foram ignoradas."
        )
        frame = frame.loc[~outside_year].copy()
    if frame.empty:
        raise WorkbookError("nenhuma linha válida permaneceu após a validação")

    duplicate_mask = frame.duplicated(
        subset=["__subsystem_key", "ena_data"], keep="last"
    )
    duplicate_count = int(duplicate_mask.sum())
    frame = frame.loc[~duplicate_mask].copy()
    frame["__file_order"] = file_order
    frame["__sin_calculated"] = False

    period_start = frame["ena_data"].min().strftime("%d/%m/%Y")
    period_end = frame["ena_data"].max().strftime("%d/%m/%Y")
    subsystem_count = int(frame["__subsystem_key"].nunique())
    report = {
        "Arquivo": filename,
        "Ano": year,
        "Período lido": f"{period_start} a {period_end}",
        "Linhas diárias": len(frame),
        "Subsistemas": subsystem_count,
        "Duplicatas removidas": duplicate_count,
        "Situação": f"Processado ({source_format})",
    }
    return frame[
        [
            "id_subsistema",
            "nom_subsistema",
            "ena_data",
            *METRIC_LABELS.keys(),
            "__subsystem_key",
            "__subsystem_label",
            "__file_order",
            "__sin_calculated",
        ]
    ], report, warnings


def _append_sin_series(data: pd.DataFrame) -> pd.DataFrame:
    """Cria o SIN somente quando os quatro subsistemas estão presentes no dia.

    Os percentuais do SIN não são médias simples. Para cada subsistema, a MLT
    implícita é reconstruída por ``MLT_i = ENA_i / (%MLT_i / 100)``. Depois,
    ``%MLT_SIN = 100 * sum(ENA_i) / sum(MLT_i)``.
    """
    if data.empty:
        return data

    result = data.copy()
    if "__sin_calculated" not in result.columns:
        result["__sin_calculated"] = False
    result["__sin_calculated"] = result["__sin_calculated"].fillna(False).astype(bool)

    official_sin_dates = set(
        pd.to_datetime(
            result.loc[result["__subsystem_key"].eq("SIN"), "ena_data"],
            errors="coerce",
        ).dropna()
    )
    regional = result.loc[
        result["__subsystem_key"].isin(REQUIRED_SIN_SUBSYSTEMS)
    ].copy()
    if regional.empty:
        return result

    rows: list[dict[str, object]] = []
    for timestamp, group in regional.groupby("ena_data", sort=True, observed=True):
        if pd.Timestamp(timestamp) in official_sin_dates:
            continue

        available = set(group["__subsystem_key"].dropna().astype(str))
        if available != REQUIRED_SIN_SUBSYSTEMS:
            continue

        complete_group = group.loc[
            group["__subsystem_key"].isin(REQUIRED_SIN_SUBSYSTEMS)
        ].copy()
        brute_value = complete_group["ena_bruta_regiao_mwmed"].sum(min_count=4)
        stored_value = complete_group["ena_armazenavel_regiao_mwmed"].sum(min_count=4)
        brute_percent = _aggregate_percent_mlt(
            complete_group["ena_bruta_regiao_mwmed"],
            complete_group["ena_bruta_regiao_percentualmlt"],
        )
        stored_percent = _aggregate_percent_mlt(
            complete_group["ena_armazenavel_regiao_mwmed"],
            complete_group["ena_armazenavel_regiao_percentualmlt"],
        )
        if any(
            pd.isna(value)
            for value in (brute_value, stored_value, brute_percent, stored_percent)
        ):
            continue

        rows.append(
            {
                "id_subsistema": "SIN",
                "nom_subsistema": "SIN calculado",
                "ena_data": timestamp,
                "ena_bruta_regiao_mwmed": brute_value,
                "ena_bruta_regiao_percentualmlt": brute_percent,
                "ena_armazenavel_regiao_mwmed": stored_value,
                "ena_armazenavel_regiao_percentualmlt": stored_percent,
                "__subsystem_key": "SIN",
                "__subsystem_label": "SIN · ENA calculada",
                "__file_order": complete_group["__file_order"].max(),
                "__sin_calculated": True,
            }
        )

    if not rows:
        return result
    sin = pd.DataFrame(rows)
    return pd.concat([result, sin], ignore_index=True, sort=False)


def _aggregate_percent_mlt(values: pd.Series, percentages: pd.Series) -> float:
    values_numeric = pd.to_numeric(values, errors="coerce")
    percentages_numeric = pd.to_numeric(percentages, errors="coerce")
    valid = values_numeric.notna() & percentages_numeric.notna() & percentages_numeric.ne(0)
    if int(valid.sum()) != len(values_numeric):
        return float("nan")
    inferred_mlt = values_numeric.loc[valid] / (percentages_numeric.loc[valid] / 100)
    denominator = inferred_mlt.sum(min_count=1)
    numerator = values_numeric.loc[valid].sum(min_count=1)
    if pd.isna(denominator) or denominator == 0:
        return float("nan")
    return float(numerator / denominator * 100)


def _rename_aliases(frame: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for column in frame.columns:
            if column in aliases:
                rename[column] = canonical
                break
    return frame.rename(columns=rename)


def _normalize_column_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return text


def _normalize_subsystem_key(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = unicodedata.normalize("NFKD", str(value).strip().upper())
    text = "".join(character for character in text if not unicodedata.combining(character))
    compact = re.sub(r"[^A-Z0-9]", "", text)
    mapping = {
        "SIN": "SIN",
        "SE": "SE",
        "SECO": "SE",
        "SUDESTE": "SE",
        "SUDESTECENTROOESTE": "SE",
        "S": "S",
        "SUL": "S",
        "NE": "NE",
        "NORDESTE": "NE",
        "N": "N",
        "NORTE": "N",
    }
    return mapping.get(compact, compact or None)


def _normalize_subsystem_label(key: str | None, value: object) -> str:
    if key in SUBSYSTEM_FALLBACK_LABELS:
        fallback = SUBSYSTEM_FALLBACK_LABELS[key]
    else:
        fallback = key or "Subsistema"
    if pd.isna(value):
        return fallback
    text = str(value).strip()
    return text or fallback


def _to_numeric(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip()
    comma_decimal = text.str.contains(",", regex=False, na=False)
    text = text.where(~comma_decimal, text.str.replace(".", "", regex=False))
    text = text.str.replace(",", ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


def _expected_days(period_start: pd.Timestamp, granularity: Granularity) -> int:
    if granularity == "daily":
        return 1
    if granularity == "monthly":
        return calendar.monthrange(period_start.year, period_start.month)[1]
    return 366 if calendar.isleap(period_start.year) else 365
