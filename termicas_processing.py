"""Leitura, validação e agregação sem dupla contagem dos dados térmicos do ONS."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import atexit
import shutil
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq
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
    # No modo lazy, mantemos somente os Parquet no disco temporário, não
    # milhões de linhas em st.session_state.
    file_paths: tuple[Path, ...] = ()
    bounds: tuple[date, date] | None = None
    filter_options: dict[str, list[str]] = field(default_factory=dict)
    storage_dir: Path | None = None
    total_rows: int = 0


def release_thermal_cache(result: ThermalResult | None) -> None:
    """Libera arquivos de uma sessão antiga depois de um novo download."""
    if result is not None and result.storage_dir is not None:
        shutil.rmtree(result.storage_dir, ignore_errors=True)


def _file_large(path: Path) -> bool:
    if path.suffix.lower() == ".parquet":
        return pq.read_metadata(path).num_rows > 25000
    # CSV é menos compacto; bases reais superam normalmente este tamanho.
    return path.stat().st_size > 2 * 1024 * 1024


def _to_disk_inventory(files: list[tuple[str, Path]]) -> ThermalResult:
    """Converte fallbacks CSV e mantém arquivos originais em disco.

    Abre somente uma coluna por vez para inventariar valores, sem carregar o
    conjunto inteiro. A leitura analítica será sob demanda por mês e projeção.
    """
    root = Path(tempfile.mkdtemp(prefix="dadosmensaisons_termicas_"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    report: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    options: dict[str, set[str]] = {
        col: set() for col in (
            "nom_subsistema", "id_subsistema", "nom_usina",
            "nom_combustivel", "nom_tipocombustivel", "nom_tipopatamar"
        )
    }
    paths: list[Path] = []
    metrics: set[str] = set()
    minimum: pd.Timestamp | None = None
    maximum: pd.Timestamp | None = None
    row_count = 0
    try:
        for name, path in files:
            try:
                path = Path(path)
                target = root / (path.stem + ".parquet")
                if path.suffix.lower() == ".csv":
                    # Um arquivo por vez: não acumular diferentes meses na memória.
                    frame = pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
                    frame.columns = [str(col).strip().lower() for col in frame.columns]
                    for col in frame.columns:
                        if col.startswith(("val_prog", "val_verif")) or col == "val_geracaodespachada":
                            frame[col] = pd.to_numeric(
                                frame[col].astype("string").str.replace(",", ".", regex=False),
                                errors="coerce",
                            )
                    frame.to_parquet(target, index=False)
                    del frame
                elif path.suffix.lower() == ".parquet":
                    path.replace(target)
                else:
                    raise ValueError("Formato desconhecido.")
                parquet = pq.ParquetFile(target)
                names = {str(name).strip().lower(): name for name in parquet.schema_arrow.names}
                missing = REQUIRED - names.keys()
                if missing:
                    raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(sorted(missing)))
                timestamp = pd.to_datetime(
                    pq.read_table(target, columns=[names["din_instante"]])
                    .column(0).to_pandas(), errors="coerce"
                ).dropna()
                if timestamp.empty:
                    raise ValueError("Sem datas válidas.")
                start, end = timestamp.min(), timestamp.max()
                minimum = start if minimum is None else min(minimum, start)
                maximum = end if maximum is None else max(maximum, end)
                for col in options:
                    if col in names:
                        values = pq.read_table(target, columns=[names[col]]).column(0).unique().to_pylist()
                        options[col].update(str(v) for v in values if v is not None)
                for canonical, actual in names.items():
                    typ = parquet.schema_arrow.field(actual).type
                    if (canonical.startswith(("val_prog", "val_verif")) or canonical == "val_geracaodespachada") and (
                        pa.types.is_integer(typ) or pa.types.is_floating(typ) or pa.types.is_decimal(typ)
                    ):
                        metrics.add(canonical)
                report.append({
                    "Arquivo": name, "Ano": int(start.year),
                    "Linhas": int(parquet.metadata.num_rows),
                    "Datas inválidas": int(parquet.metadata.num_rows - len(timestamp)),
                    "Início": start, "Fim": end,
                    "Formato carregado": path.suffix.lower().lstrip("."),
                    "Modo": "Disco / leitura por mês",
                })
                row_count += parquet.metadata.num_rows
                paths.append(target)
            except (OSError, ValueError, TypeError, KeyError, ImportError, pa.ArrowException) as exc:
                errors.append(f"{name}: {exc}")
                target.unlink(missing_ok=True)
        if not paths or minimum is None or maximum is None:
            shutil.rmtree(root, ignore_errors=True)
            return ThermalResult(pd.DataFrame(), [], pd.DataFrame(report), errors, warnings)
        metric_columns = [m for m in PRIMARY_METRICS if m in metrics]
        metric_columns.extend(sorted(metrics - set(metric_columns)))
        return ThermalResult(
            hourly=pd.DataFrame(), metric_columns=metric_columns,
            file_report=pd.DataFrame(report), errors=errors, warnings=warnings,
            file_paths=tuple(paths), bounds=(minimum.date(), maximum.date()),
            filter_options={col: sorted(values) for col, values in options.items()},
            storage_dir=root, total_rows=row_count,
        )
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
    raise ValueError("Formato não suportado.")


def process_thermal_files(files: Iterable[tuple[str, Path]]) -> ThermalResult:
    files = list(files)
    if any(_file_large(Path(path)) for _, path in files):
        return _to_disk_inventory(files)
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
