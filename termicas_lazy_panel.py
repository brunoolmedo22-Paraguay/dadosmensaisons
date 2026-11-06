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
    # Filtro temporal é aplicado pelo PyArrow antes de expandir a tabela em Pandas.
    frame = pd.read_parquet(
        path, columns=columns,
        filters=[
            ("din_instante", ">=", pd.Timestamp(start)),
            ("din_instante", "<", pd.Timestamp(end) + pd.Timedelta(days=1)),
        ],
    )
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "din_instante" not in frame:
        raise ValueError(f"{path.name}: coluna de data ausente")
    frame["din_instante"] = pd.to_datetime(frame["din_instante"], errors="coerce")
    mask = frame["din_instante"].between(
        pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1), inclusive="left",
    )
    for column, values in filters.items():
        if values:
            if column not in frame:
                mask &= False
            else:
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
    """Uma única relação DuckDB sobre todos os Parquet, sem concatenação Pandas."""
    from termicas_duckdb import query_thermal
    return query_thermal(
        result, start, end, filters, granularity, metrics,
        raw_mode=raw_mode, export_raw=export_raw,
    )

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
                    value=minimum, min_value=minimum,
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
                result, start, end, filters, granularity, chosen, raw_mode=view=="raw", export_raw=False
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
                from termicas_duckdb import export_thermal
                # A exportação só ocorre quando solicitada: Streamlit não
                # recompõe milhões de registros em cada mudança de filtro.
                signature = repr((
                    start.isoformat(), end.isoformat(),
                    sorted((key, tuple(val)) for key, val in filters.items()),
                ))
                if st.button(
                    tr("Preparar CSV completo do intervalo filtrado", "Preparar CSV completo del intervalo filtrado"),
                    key="thermal_prepare_filtered_csv",
                ):
                    with st.spinner(tr("Gerando CSV.GZ completo...", "Generando CSV.GZ completo...")):
                        path = export_thermal(result, "csv.gz", start=start, end=end, filters=filters)
                    st.session_state["thermal_filtered_export"] = (signature, str(path))
                prepared = st.session_state.get("thermal_filtered_export")
                if prepared and prepared[0] == signature and Path(prepared[1]).is_file():
                    path = Path(prepared[1])
                    st.download_button(
                        tr("Baixar todas as linhas filtradas (CSV.GZ)", "Descargar todas las filas filtradas (CSV.GZ)"),
                        data=path.read_bytes(), file_name="ons_termicas_filtrado.csv.gz",
                        mime="application/gzip", key="thermal_lazy_raw_csv",
                    )
        # Download da união integral de TODOS os meses carregados, sem
        # restringir às datas/colunas exibidas nos gráficos.
        from termicas_duckdb import export_thermal
        with st.container(border=True):
            st.subheader(tr("Tabela completa concatenada", "Tabla completa concatenada"))
            st.caption(tr(
                "Todos os arquivos Parquet carregados, todas as usinas, linhas e colunas "
                "do ONS em um único arquivo. As mudanças de esquema entre anos são "
                "unificadas por nome de coluna, preservando valores ausentes.",
                "Todos los archivos Parquet cargados, todas las centrales, filas y "
                "columnas del ONS en un único archivo. Los cambios de esquema se "
                "unifican por nombre de columna, preservando los valores faltantes.",
            ))
            if st.button(
                tr("Preparar Parquet completo concatenado", "Preparar Parquet completo concatenado"),
                key="thermal_prepare_all_parquet",
            ):
                with st.spinner(tr("Concatenando os arquivos...", "Concatenando los archivos...")):
                    path = export_thermal(result, "parquet")
                st.session_state["thermal_all_parquet_path"] = str(path)
            prepared_path = st.session_state.get("thermal_all_parquet_path")
            if prepared_path and Path(prepared_path).is_file():
                path = Path(prepared_path)
                st.download_button(
                    tr("Baixar tabela completa (Parquet)", "Descargar tabla completa (Parquet)"),
                    data=path.read_bytes(), file_name="ons_termicas_concatenado.parquet",
                    mime="application/octet-stream", key="thermal_all_parquet_download",
                )
            if st.button(
                tr("Preparar CSV completo concatenado", "Preparar CSV completo concatenado"),
                key="thermal_prepare_all_csv",
            ):
                with st.spinner(tr("Gerando CSV completo...", "Generando CSV completo...")):
                    path = export_thermal(result, "csv.gz")
                st.session_state["thermal_all_csv_path"] = str(path)
            prepared_csv = st.session_state.get("thermal_all_csv_path")
            if prepared_csv and Path(prepared_csv).is_file():
                path = Path(prepared_csv)
                st.download_button(
                    tr("Baixar tabela completa (CSV.GZ)", "Descargar tabla completa (CSV.GZ)"),
                    data=path.read_bytes(), file_name="ons_termicas_concatenado.csv.gz",
                    mime="application/gzip", key="thermal_all_csv_download",
                )
        with st.expander(tr("Arquivos processados", "Archivos procesados")):
            st.dataframe(result.file_report, hide_index=True, width="stretch")
