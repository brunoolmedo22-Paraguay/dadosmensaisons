"""Consolidação lógica de Parquet térmico via DuckDB, sem DataFrame multi-ano.

O SQL consulta todos os arquivos de um período como uma só relação, inclusive
colunas presentes apenas em alguns meses (union_by_name). Resultados grandes
são materializados diretamente em disco por COPY, não em Pandas.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal
import re

import duckdb
import pandas as pd

from termicas_processing import FREQUENCIES, ThermalResult


_ALLOWED_DIMENSIONS = {
    "nom_subsistema", "id_subsistema", "nom_usina",
    "nom_combustivel", "nom_tipocombustivel", "nom_tipopatamar",
}
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _lit(value: object) -> str:
    """SQL literal quoting for internal paths and user-selected filter values."""
    return "'" + str(value).replace("'", "''") + "'"


def _column(value: str) -> str:
    if not _NAME.fullmatch(value):
        raise ValueError("Identificador SQL inválido")
    return '"' + value + '"'


@contextmanager
def _database(result: ThermalResult) -> Iterator[tuple[duckdb.DuckDBPyConnection, str]]:
    if not result.file_paths or result.storage_dir is None:
        raise ValueError("Arquivos térmicos indisponíveis")
    if not all(path.is_file() for path in result.file_paths):
        raise ValueError("Arquivos da consulta anterior não estão mais disponíveis")
    connection = duckdb.connect(database=":memory:")
    try:
        # DuckDB faz spill para o diretório temporário. Evita múltiplas
        # buffers simultâneas e cópias de blocos gigantes na exportação.
        connection.execute("SET memory_limit='384MB'")
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute("SET temp_directory=" + _lit(result.storage_dir / "duckdb_tmp"))
        # A pasta de sessão contém apenas arquivos Parquet da consulta.
        source = (
            "read_parquet(" +
            _lit(str(result.storage_dir / "*.parquet")) +
            ", union_by_name=true)"
        )
        yield connection, source
    finally:
        connection.close()


def _where(
    start: date, end: date, filters: dict[str, list[str]],
) -> str:
    if start > end:
        raise ValueError("Datas invertidas")
    lower = _lit(f"{start.isoformat()} 00:00:00")
    upper = _lit(f"{(end + timedelta(days=1)).isoformat()} 00:00:00")
    conditions = [
        f"din_instante >= TIMESTAMP {lower}",
        f"din_instante < TIMESTAMP {upper}",
    ]
    for name, selected in filters.items():
        if name not in _ALLOWED_DIMENSIONS:
            raise ValueError(f"Filtro não permitido: {name}")
        if selected:
            values = ", ".join(_lit(value) for value in selected)
            conditions.append(f"CAST({_column(name)} AS VARCHAR) IN ({values})")
    return " AND ".join(conditions)


def _metrics(result: ThermalResult, metrics: list[str]) -> list[str]:
    requested = list(dict.fromkeys(metrics))
    for name in requested:
        if name not in result.metric_columns or not _NAME.fullmatch(name):
            raise ValueError(f"Grandeza não permitida: {name}")
    return requested


def _numeric(column: str) -> str:
    identifier = _column(column)
    # Algumas edições do Parquet ONS armazenam a grandeza como VARCHAR.
    # Tenta a conversão direta e aceita vírgula decimal em arquivos legados.
    return (
        f"COALESCE(TRY_CAST({identifier} AS DOUBLE), "
        f"TRY_CAST(REPLACE(CAST({identifier} AS VARCHAR), ',', '.') AS DOUBLE))"
    )


def query_thermal(
    result: ThermalResult,
    start: date,
    end: date,
    filters: dict[str, list[str]],
    granularity: str,
    metrics: list[str],
    *,
    raw_mode: bool = False,
    export_raw: bool = True,
) -> tuple[pd.DataFrame, pd.Series, int, int, int, pd.DataFrame, bytes | None]:
    """Retorna médias, ranking, KPIs e prévia; todos os meses são consultados."""
    if granularity not in FREQUENCIES:
        raise ValueError("Discretização desconhecida")
    metric_columns = _metrics(result, metrics)
    if not metric_columns:
        return pd.DataFrame(), pd.Series(dtype=float), 0, 0, 0, pd.DataFrame(), None
    where = _where(start, end, filters)
    precision = {
        "hourly": "hour", "daily": "day", "monthly": "month", "yearly": "year",
    }[granularity]
    with _database(result) as (conn, source):
        sums = ", ".join(
            f"SUM({_numeric(metric)}) AS {_column(metric)}"
            for metric in metric_columns
        )
        averages = ", ".join(
            f"AVG({_column(metric)}) AS {_column(metric)}"
            for metric in metric_columns
        )
        summary_sql = f"""
            WITH hourly AS (
                SELECT date_trunc('hour', din_instante) AS instante, {sums}
                FROM {source}
                WHERE {where}
                GROUP BY 1
            )
            SELECT date_trunc('{precision}', instante) AS "Período",
                   COUNT(*) AS "Horas observadas", {averages}
            FROM hourly
            GROUP BY 1 ORDER BY 1
        """
        summary = conn.execute(summary_sql).df()
        if summary.empty:
            return pd.DataFrame(), pd.Series(dtype=float), 0, 0, 0, pd.DataFrame(), None
        stats_sql = f"""
            SELECT count(*) AS rows_count,
                count(DISTINCT nom_usina) AS plant_count,
                count(DISTINCT date_trunc('hour', din_instante)) AS hour_count
            FROM {source} WHERE {where}
        """
        nrows, nplants, nhours = map(int, conn.execute(stats_sql).fetchone())
        # Ranking visual: média por registro de cada usina, sem COUNT(DISTINCT)
        # de milhões de chaves (usina, hora), que causava OOM em 256 MB.
        # A série temporal e suas médias permanecem agregadas corretamente
        # por hora sobre todas as usinas, de forma independente do ranking.
        numeric = _numeric(metric_columns[0])
        ranking_sql = f"""
            SELECT nom_usina, AVG({numeric}) AS period_mean
            FROM {source}
            WHERE {where}
            GROUP BY nom_usina
            HAVING AVG({numeric}) IS NOT NULL
            ORDER BY period_mean DESC NULLS LAST
            LIMIT 15
        """
        ranking_frame = conn.execute(ranking_sql).df()
        ranking = (
            ranking_frame.set_index("nom_usina")["period_mean"]
            .sort_values(ascending=True)
            if not ranking_frame.empty else pd.Series(dtype=float)
        )
        preview = (
            conn.execute(f"SELECT * FROM {source} WHERE {where} LIMIT 5000").df()
            if raw_mode else pd.DataFrame()
        )
        payload = None
        if raw_mode and export_raw:
            path = export_thermal(
                result, "csv.gz", start=start, end=end, filters=filters
            )
            payload = path.read_bytes()
        return summary, ranking, nrows, nplants, nhours, preview, payload


def export_thermal(
    result: ThermalResult,
    file_format: Literal["parquet", "csv.gz"],
    *,
    start: date | None = None,
    end: date | None = None,
    filters: dict[str, list[str]] | None = None,
) -> Path:
    """Materializa uma única tabela integral concatenada diretamente em disco.

    Nenhuma linha nem coluna é descartada; union_by_name preenche valores
    ausentes com NULL quando o ONS mudou o esquema entre os meses.
    """
    if result.storage_dir is None or result.bounds is None:
        raise ValueError("Sessão térmica inválida")
    start = start or result.bounds[0]
    end = end or result.bounds[1]
    where = _where(start, end, filters or {})
    suffix = "parquet" if file_format == "parquet" else "csv.gz"
    output = result.storage_dir / ("export_termicas_completo." + suffix)
    # Não colocar exportação no glob da origem! O nome export_ não coincide
    # com o padrão dos arquivos oficiais, mas o glob abaixo usa *.parquet.
    # Por isso deixamos saídas em um subdiretório separado.
    exports = result.storage_dir / "exports"
    exports.mkdir(exist_ok=True)
    output = exports / ("termicas_concatenado." + suffix)
    with _database(result) as (conn, source):
        query = f"SELECT * FROM {source} WHERE {where}"
        output.unlink(missing_ok=True)
        if file_format == "parquet":
            # Row groups pequenos impedem que COPY retenha ~centenas de MB
            # em buffers de escrita para as ~47 colunas da base do ONS.
            options = "FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 8192"
        elif file_format == "csv.gz":
            options = "FORMAT CSV, HEADER TRUE, DELIMITER ';', COMPRESSION GZIP"
        else:
            raise ValueError("Formato não autorizado")
        conn.execute(f"COPY ({query}) TO {_lit(output)} ({options})")
    return output
