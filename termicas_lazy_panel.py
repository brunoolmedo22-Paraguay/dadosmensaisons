"""Painel térmico multi-ano com arquivos em disco e leitura de um mês por vez.

A UI nunca mantém o conjunto completo de registros em st.session_state.
"""
from __future__ import annotations

import gzip
import os
from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import plotly.graph_objects as go
import pyarrow.parquet as pq
import streamlit as st

from termicas_processing import FREQUENCIES, METRIC_LABELS, ThermalResult


def _translated(language: str, pt: str, es: str) -> str:
    return es if language == "ES" else pt


def _available(path: Path, candidates: list[str]) -> list[str]:
    names = set(pq.ParquetFile(path).schema_arrow.names)
    return [name for name in dict.fromkeys(candidates) if name in names]


def _subset_month(
    path: Path, start: date, end: date,
    filters: dict[str, list[str]], metrics: list[str], *, raw: bool = False,
) -> pd.DataFrame:
    """Projeta só colunas necessárias; mantém uma partição em RAM por vez."""
    identity = [
        "din_instante", "id_subsistema", "nom_usina",
        "cod_usinaplanejamento", "ceg", "din_publicacao",
    ]
    requested = identity + list(filters) + metrics
    columns = None if raw else _available(path, requested)
    frame = pd.read_parquet(path, columns=columns)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "din_instante" not in frame:
        raise ValueError(f"{path.name}: coluna de data ausente")
    frame["din_instante"] = pd.to_datetime(frame["din_instante"], errors="coerce")
    mask = frame["din_instante"].between(
        pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1), inclusive="left",
    )
    for column, values in filters.items():
        if values and column in frame:
            mask &= frame[column].astype(str).isin(values)
    frame = frame.loc[mask].copy()
    del mask
    if frame.empty:
        return frame
    identity = [name for name in identity if name in frame and name != "din_publicacao"]
    if "din_publicacao" in frame:
        frame["din_publicacao"] = pd.to_datetime(frame["din_publicacao"], errors="coerce")
        frame = frame.sort_values("din_publicacao", kind="stable")
    if identity:
        frame = frame.drop_duplicates(identity, keep="last")
    for metric in metrics:
        if metric in frame:
            frame[metric] = pd.to_numeric(frame[metric], errors="coerce")
    return frame


def summarize_from_disk(
    result: ThermalResult, start: date, end: date,
    filters: dict[str, list[str]], granularity: str, metrics: list[str],
    *, raw_mode: bool = False,
) -> tuple[pd.DataFrame, pd.Series, int, int, int, pd.DataFrame, bytes | None]:
    """Calcula médias sem concatenação de meses e preserva CSV integral opcional.

    Retorna (médias, ranking, nº registros, nº usinas, nº horas, amostra, export).
    """
    if granularity not in FREQUENCIES:
        raise ValueError("Discretização desconhecida")
    hourly_parts: list[pd.DataFrame] = []
    plant_parts: list[pd.DataFrame] = []
    row_count = 0
    plant_set: set[str] = set()
    previews: list[pd.DataFrame] = []
    sample_rows = 0
    gzip_path: Path | None = None
    archive = None
    try:
        if raw_mode:
            handle = NamedTemporaryFile(prefix="ons_termica_export_", suffix=".csv.gz", delete=False)
            gzip_path = Path(handle.name)
            handle.close()
            archive = gzip.open(gzip_path, "wt", encoding="utf-8-sig", newline="")
        first = True
        for path in result.file_paths:
            # Arquivos publicados por ano/mês. Evita ler meses fora do filtro,
            # usando metadados do nome e datas do arquivo, sem abrir todas as linhas.
            if "_DESPACHO-2_" in path.name.upper():
                import re
                matched = re.search(r"DESPACHO-2_(\d{4})_(\d{2})", path.name.upper())
                if matched:
                    y, m = map(int, matched.groups())
                    month_start = date(y, m, 1)
                    month_end = (
                        date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
                    )
                    if month_start > end or month_end <= start:
                        continue
            frame = _subset_month(path, start, end, filters, metrics, raw=raw_mode)
            if frame.empty:
                continue
            row_count += len(frame)
            if "nom_usina" in frame:
                plant_set.update(frame["nom_usina"].dropna().astype(str).unique())
            hourly_parts.append(
                frame.groupby("din_instante", sort=True)[metrics].sum(min_count=1)
            )
            if "nom_usina" in frame and metrics:
                metric = metrics[0]
                plant_hour = (
                    frame.groupby(["nom_usina", "din_instante"], sort=False)[metric]
                    .sum(min_count=1)
                )
                stats = plant_hour.groupby(level=0).agg(["sum", "count"])
                plant_parts.append(stats)
            if raw_mode:
                if sample_rows < 5000:
                    preview = frame.head(5000 - sample_rows)
                    previews.append(preview)
                    sample_rows += len(preview)
                frame.to_csv(archive, index=False, sep=";", decimal=",", header=first,
                             date_format="%Y-%m-%d %H:%M:%S")
                first = False
            del frame
        if archive is not None:
            archive.close()
            archive = None
        if not hourly_parts:
            return (pd.DataFrame(), pd.Series(dtype=float), 0, 0, 0,
                    pd.DataFrame(), None)
        # A soma é feita por hora; a média temporal não depende do nº de usinas.
        by_hour = pd.concat(hourly_parts).groupby(level=0, sort=True).sum(min_count=1)
        hourly_count = len(by_hour)
        average = by_hour.resample(FREQUENCIES[granularity]).mean()
        counts = by_hour.resample(FREQUENCIES[granularity]).size()
        average.insert(0, "Horas observadas", counts)
        average = average.loc[counts.gt(0)].rename_axis("Período").reset_index()
        if plant_parts:
            plant = pd.concat(plant_parts).groupby(level=0).sum()
            ranking = (plant["sum"] / plant["count"].where(plant["count"].gt(0))).dropna().nlargest(15).sort_values()
        else:
            ranking = pd.Series(dtype=float)
        preview = pd.concat(previews, ignore_index=True) if previews else pd.DataFrame()
        payload = gzip_path.read_bytes() if gzip_path is not None else None
        return average, ranking, row_count, len(plant_set), hourly_count, preview, payload
    finally:
        if archive is not None:
            archive.close()
        if gzip_path is not None:
            gzip_path.unlink(missing_ok=True)


def render_lazy_thermal_panel(result: ThermalResult, language: str = "PT") -> None:
    tr = lambda pt, es: _translated(language, pt, es)
    assert result.bounds is not None
    minimum, maximum = result.bounds
    options = result.filter_options
    with st.container(border=True, key="thermal_lazy_panel"):
        st.markdown('<div class="panel-kicker">ONS · GERAÇÃO TÉRMICA</div>', unsafe_allow_html=True)
        st.subheader(tr("Geração Térmica por Motivo de Despacho", "Generación térmica por motivo de despacho"))
        st.caption(tr(
            "Os arquivos Parquet permanecem no disco temporário. Cada mês é processado "
            "separadamente, evitando carregar dois anos completos na memória.",
            "Los archivos Parquet permanecen en el disco temporal. Cada mes se procesa "
            "por separado, evitando cargar dos años completos en memoria.",
        ))
        with st.container(border=True):
            controls = st.columns(4, gap="small")
            with controls[0]:
                start = st.date_input(tr("Data inicial", "Fecha inicial"),
                    value=max(minimum, maximum-timedelta(days=31)), min_value=minimum,
                    max_value=maximum, key="thermal_lazy_start")
            with controls[1]:
                end = st.date_input(tr("Data final", "Fecha final"),
                    value=maximum, min_value=minimum, max_value=maximum,
                    key="thermal_lazy_end")
            with controls[2]:
                granularity = st.selectbox(tr("Discretização", "Resolución"),
                    options=("hourly", "daily", "monthly", "yearly"), index=2,
                    format_func=lambda x: {
                        "hourly": tr("Horária", "Horaria"),
                        "daily": tr("Diária", "Diaria"),
                        "monthly": tr("Mensal", "Mensual"),
                        "yearly": "Anual",
                    }[x], key="thermal_lazy_granularity")
            with controls[3]:
                view = st.selectbox(tr("Visualização", "Visualización"),
                    options=("summary", "raw"),
                    format_func=lambda x: tr(
                        "Médias por período" if x == "summary" else "Registros originais",
                        "Promedios por período" if x == "summary" else "Registros originales"),
                    key="thermal_lazy_view")
            if start > end:
                st.error(tr("Data inicial posterior à final.", "Fecha inicial posterior a la final."))
                return
            dimensions = [
                ("nom_subsistema", "Subsistema", "Subsistema"),
                ("nom_usina", "Usina", "Central"),
                ("nom_combustivel", "Combustível", "Combustible"),
                ("nom_tipopatamar", "Patamar de carga", "Nivel de carga"),
            ]
            filters: dict[str, list[str]] = {}
            filter_columns = st.columns(4, gap="small")
            for container, (key, pt, es) in zip(filter_columns, dimensions):
                with container:
                    available = options.get(key, [])
                    if not available and key == "nom_combustivel":
                        key = "nom_tipocombustivel"
                        available = options.get(key, [])
                    if available:
                        filters[key] = st.multiselect(
                            tr(pt, es) + tr(" (vazio = todos)", " (vacío = todos)"),
                            available, key="thermal_lazy_filter_" + key)
            metric_columns = result.metric_columns
            defaults = [m for m in ("val_proggeracao", "val_verifgeracao") if m in metric_columns]
            chosen = st.multiselect(
                tr("Grandezas / motivos de despacho", "Magnitudes / motivos de despacho"),
                options=metric_columns, default=defaults or metric_columns[:1],
                format_func=lambda m: METRIC_LABELS.get(m, m),
                key="thermal_lazy_metrics")
        if not chosen:
            st.warning(tr("Selecione uma grandeza.", "Seleccione una magnitud."))
            return
        with st.spinner(tr("Processando arquivos mensais...", "Procesando archivos mensuales...")):
            summary, ranking, nrows, nplants, nhours, preview, raw_csv = summarize_from_disk(
                result, start, end, filters, granularity, chosen, raw_mode=view=="raw"
            )
        if summary.empty:
            st.info(tr("Nenhum dado encontrado no intervalo.", "Sin datos para el intervalo."))
            return
        st.info(tr(
            "Média das horas observadas; as horas sem dados não são preenchidas com zero. "
            "Motivos de despacho diferentes não devem ser somados entre si.",
            "Promedio de horas observadas; las horas faltantes no se completan con cero. "
            "Los motivos de despacho diferentes no deben sumarse.",
        ), icon="ℹ️")
        kpis = st.columns(4)
        kpis[0].metric(tr("Registros", "Registros"), f"{nrows:,}")
        kpis[1].metric(tr("Usinas", "Centrales"), nplants)
        kpis[2].metric(tr("Horas observadas", "Horas observadas"), nhours)
        kpis[3].metric(tr("Períodos", "Períodos"), len(summary))
        with st.container(border=True):
            st.subheader(tr("Evolução da geração térmica", "Evolución de la generación térmica"))
            fig=go.Figure()
            colors=["#2563eb", "#e11d48", "#059669", "#d97706", "#7c3aed", "#0891b2"]
            for i, metric in enumerate(chosen):
                fig.add_trace(go.Scatter(
                    x=summary["Período"], y=summary[metric],
                    mode="lines+markers" if len(summary)<=48 else "lines",
                    name=METRIC_LABELS.get(metric, metric), connectgaps=False,
                    line={"color": colors[i%len(colors)], "width": 2},
                ))
            fig.update_layout(template="plotly_white", height=400,
                margin=dict(l=20,r=20,t=20,b=35), hovermode="x unified",
                xaxis_title=tr("Data","Fecha"), yaxis_title="MWmed",
                legend={"orientation":"h","y":-0.22})
            st.plotly_chart(fig, width="stretch", key="thermal_lazy_timeseries", config={"displaylogo":False})
        if not ranking.empty:
            with st.container(border=True):
                st.subheader(tr("Usinas · maiores médias no período", "Centrales · mayores promedios del período"))
                st.caption(METRIC_LABELS.get(chosen[0], chosen[0]))
                fig=go.Figure(go.Bar(x=ranking.values, y=ranking.index, orientation="h", marker_color="#0e7490"))
                fig.update_layout(template="plotly_white",
                    height=max(260, 32*len(ranking)+80), margin=dict(l=20,r=20,t=15,b=25),
                    xaxis_title="MWmed", yaxis_title="")
                st.plotly_chart(fig, width="stretch", key="thermal_lazy_ranking", config={"displaylogo":False})
        with st.container(border=True):
            st.subheader(tr("Tabela e exportação", "Tabla y exportación"))
            if view == "summary":
                st.dataframe(summary.rename(columns={m: METRIC_LABELS.get(m,m) for m in chosen}),
                             hide_index=True, width="stretch", height=400)
                st.download_button(tr("Baixar médias em CSV", "Descargar promedios CSV"),
                    data=summary.to_csv(index=False, sep=";", decimal=",",
                        date_format="%Y-%m-%d %H:%M:%S").encode("utf-8-sig"),
                    file_name=f"ons_termicas_medias_{granularity}.csv",
                    mime="text/csv", key="thermal_lazy_summary_csv")
            else:
                st.caption(tr(
                    "Amostra de 5.000 linhas na tela; o CSV.GZ contém todos os registros filtrados.",
                    "Muestra de 5.000 filas en pantalla; el CSV.GZ contiene todos los registros filtrados.",
                ))
                st.dataframe(preview, hide_index=True, width="stretch", height=400)
                if raw_csv is not None:
                    st.download_button(tr("Baixar dados originais (CSV.GZ)", "Descargar datos originales (CSV.GZ)"),
                        data=raw_csv, file_name="ons_termicas_registros_filtrados.csv.gz",
                        mime="application/gzip", key="thermal_lazy_raw_csv")
        with st.expander(tr("Arquivos processados", "Archivos procesados")):
            st.dataframe(result.file_report, hide_index=True, width="stretch")
