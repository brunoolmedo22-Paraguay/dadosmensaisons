"""Painel independente de Geração Térmica por Motivo de Despacho."""
from __future__ import annotations

from datetime import timedelta
from io import BytesIO
import gzip

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from termicas_processing import METRIC_LABELS, ThermalResult, aggregate_thermal


def _label(metric: str, language: str) -> str:
    # Códigos oficiais permanecem disponíveis para grandezas não mapeadas.
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, sep=";", decimal=",", date_format="%Y-%m-%d %H:%M:%S").encode("utf-8-sig")


def _csv_gzip(frame: pd.DataFrame) -> bytes:
    """Exportação integral comprimida, sem criar uma cópia CSV gigante em RAM."""
    buffer = BytesIO()
    with gzip.open(buffer, mode="wt", encoding="utf-8-sig", newline="") as output:
        frame.to_csv(
            output, index=False, sep=";", decimal=",",
            date_format="%Y-%m-%d %H:%M:%S",
        )
    return buffer.getvalue()


def render_thermal_panel(result: ThermalResult, language: str = "PT") -> None:
    if result.file_paths:
        from termicas_lazy_panel import render_lazy_thermal_panel
        return render_lazy_thermal_panel(result, language)
    es = language == "ES"
    text = lambda pt, es_text: es_text if es else pt
    records = result.hourly
    with st.container(border=True, key="thermal_panel"):
        st.markdown('<div class="panel-kicker">ONS · GERAÇÃO TÉRMICA</div>', unsafe_allow_html=True)
        st.subheader(text("Geração Térmica por Motivo de Despacho", "Generación térmica por motivo de despacho"))
        st.caption(text(
            "Séries oficiais horárias de geração programada e verificada por usina. "
            "Médias diárias, mensais e anuais calculadas após somar as usinas de cada hora.",
            "Series oficiales horarias de generación programada y verificada por central. "
            "Promedios diarios, mensuales y anuales calculados después de sumar las centrales de cada hora.",
        ))
        if records.empty:
            st.warning(text("Nenhum dado térmico foi processado.", "No se procesaron datos térmicos."))
            return

        minimum = records["din_instante"].min().date()
        maximum = records["din_instante"].max().date()
        with st.container(border=True):
            st.markdown("**" + text("Filtros da análise", "Filtros del análisis") + "**")
            cols = st.columns([1, 1, 1, 1], gap="small")
            default_start = max(minimum, maximum - timedelta(days=31))
            with cols[0]:
                start = st.date_input(
                    text("Data inicial", "Fecha inicial"),
                    value=default_start,
                    min_value=minimum, max_value=maximum,
                    key="thermal_start_date",
                )
            with cols[1]:
                end = st.date_input(
                    text("Data final", "Fecha final"),
                    value=maximum,
                    min_value=minimum, max_value=maximum,
                    key="thermal_end_date",
                )
            with cols[2]:
                granularity = st.selectbox(
                    text("Discretização", "Resolución"),
                    options=("hourly", "daily", "monthly", "yearly"),
                    index=2,
                    format_func=lambda x: {
                        "hourly": text("Horária", "Horaria"),
                        "daily": text("Diária", "Diaria"),
                        "monthly": text("Mensal", "Mensual"),
                        "yearly": text("Anual", "Anual"),
                    }[x],
                    key="thermal_granularity",
                )
            with cols[3]:
                view = st.selectbox(
                    text("Visualização", "Visualización"),
                    options=("summary", "raw"),
                    format_func=lambda x: text(
                        "Médias por período" if x == "summary" else "Registros originais",
                        "Promedios por período" if x == "summary" else "Registros originales",
                    ),
                    key="thermal_view",
                )
            if start > end:
                st.error(text("Data inicial posterior à data final.", "Fecha inicial posterior a la final."))
                return

            time_mask = records["din_instante"].between(
                pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1),
                inclusive="left",
            )
            base = records.loc[time_mask]
            filters = st.columns(4, gap="small")
            with filters[0]:
                subsystems = sorted(base["nom_subsistema"].dropna().astype(str).unique().tolist()) if "nom_subsistema" in base else sorted(base["id_subsistema"].dropna().astype(str).unique().tolist())
                subsys_key = "nom_subsistema" if "nom_subsistema" in base else "id_subsistema"
                chosen_subsystems = st.multiselect(
                    text("Subsistema (vazio = todos)", "Subsistema (vacío = todos)"),
                    options=subsystems, key="thermal_subsystems",
                )
            if chosen_subsystems:
                base = base.loc[base[subsys_key].astype(str).isin(chosen_subsystems)]
            with filters[1]:
                fuels = sorted(base["nom_tipocombustivel"].dropna().astype(str).unique().tolist()) if "nom_tipocombustivel" in base else []
                chosen_fuels = st.multiselect(
                    text("Combustível", "Combustible"),
                    options=fuels, key="thermal_fuels",
                )
            if chosen_fuels and "nom_tipocombustivel" in base:
                base = base.loc[base["nom_tipocombustivel"].astype(str).isin(chosen_fuels)]
            with filters[2]:
                plants = sorted(base["nom_usina"].dropna().astype(str).unique().tolist())
                chosen_plants = st.multiselect(
                    text("Usina (vazio = todas)", "Central (vacío = todas)"),
                    options=plants, key="thermal_plants",
                )
            if chosen_plants:
                base = base.loc[base["nom_usina"].astype(str).isin(chosen_plants)]
            with filters[3]:
                tiers = sorted(base["nom_tipopatamar"].dropna().astype(str).unique().tolist()) if "nom_tipopatamar" in base else []
                chosen_tiers = st.multiselect(
                    text("Patamar de carga", "Nivel de carga"),
                    options=tiers, key="thermal_tiers",
                )
            if chosen_tiers and "nom_tipopatamar" in base:
                base = base.loc[base["nom_tipopatamar"].astype(str).isin(chosen_tiers)]

            available_metrics = result.metric_columns
            defaults = [metric for metric in ("val_proggeracao", "val_verifgeracao") if metric in available_metrics]
            selected_metrics = st.multiselect(
                text("Grandezas / motivos de despacho (MWmed)", "Magnitudes / motivos de despacho (MWmed)"),
                options=available_metrics,
                default=defaults or available_metrics[:1],
                format_func=lambda metric: _label(metric, language),
                key="thermal_metrics",
            )
        if base.empty:
            st.info(text("Nenhuma linha corresponde aos filtros.", "Ningún registro coincide con los filtros."))
            return
        if not selected_metrics:
            st.warning(text("Selecione uma grandeza.", "Seleccione una magnitud."))
            return
        if "val_proggeracao" in selected_metrics and "val_verifgeracao" in selected_metrics:
            st.caption(text(
                "Programação e verificação são séries distintas; não devem ser somadas.",
                "Programación y verificación son series distintas; no deben sumarse.",
            ))
        st.info(text(
            "Os motivos de despacho são categorias fornecidas separadamente pelo ONS, "
            "podendo incluir classificações sobrepostas. Não somar as colunas entre si. "
            "Os períodos incompletos usam apenas as horas observadas.",
            "Los motivos de despacho pueden incluir clasificaciones superpuestas. "
            "No sumar las columnas entre sí. Los períodos incompletos emplean solo las horas observadas.",
        ), icon="ℹ️")

        summary = aggregate_thermal(base, granularity, selected_metrics)
        nums = st.columns(4, gap="small")
        nums[0].metric(text("Registros", "Registros"), f"{len(base):,}")
        nums[1].metric(text("Usinas", "Centrales"), base["nom_usina"].nunique())
        nums[2].metric(text("Horas observadas", "Horas observadas"), base["din_instante"].nunique())
        nums[3].metric(text("Períodos", "Períodos"), len(summary))

        with st.container(border=True):
            st.subheader(text("Evolução da geração térmica", "Evolución de la generación térmica"))
            if not summary.empty:
                fig = go.Figure()
                palette = ["#2563eb", "#e11d48", "#059669", "#d97706", "#7c3aed", "#0891b2"]
                for index, metric in enumerate(selected_metrics):
                    fig.add_trace(go.Scatter(
                        x=summary["Período"], y=summary[metric],
                        mode="lines+markers" if len(summary) <= 48 else "lines",
                        name=_label(metric, language), connectgaps=False,
                        line={"color": palette[index % len(palette)], "width": 2},
                    ))
                fig.update_layout(
                    template="plotly_white", height=400, margin=dict(l=20, r=20, t=20, b=35),
                    hovermode="x unified", xaxis_title=text("Data", "Fecha"),
                    yaxis_title="MWmed", legend={"orientation": "h", "y": -0.22},
                )
                st.plotly_chart(fig, width="stretch", key="thermal_timeseries", config={"displaylogo": False})

        # Ranking simples, para a grandeza ativa. Cada usina recebe média das
        # suas horas observadas, não média por linha do CSV.
        metric = selected_metrics[0]
        by_plant = (
            base.groupby(["nom_usina", "din_instante"], sort=False)[metric]
            .sum(min_count=1).groupby(level=0).mean()
            .dropna().nlargest(15).sort_values()
        )
        if not by_plant.empty:
            with st.container(border=True):
                st.subheader(text("Usinas · maiores médias no período", "Centrales · mayores promedios del período"))
                st.caption(_label(metric, language))
                bar = go.Figure(go.Bar(
                    x=by_plant.values, y=by_plant.index,
                    orientation="h", marker_color="#0e7490",
                ))
                bar.update_layout(
                    template="plotly_white", height=max(260, 32 * len(by_plant) + 80),
                    margin=dict(l=25, r=20, t=15, b=25), xaxis_title="MWmed",
                    yaxis_title="",
                )
                st.plotly_chart(bar, width="stretch", key="thermal_ranking", config={"displaylogo": False})

        with st.container(border=True):
            st.subheader(text("Tabela e exportação", "Tabla y exportación"))
            if view == "summary":
                displayed = summary.copy()
                displayed["Período"] = pd.to_datetime(displayed["Período"]).dt.strftime(
                    "%d/%m/%Y %H:%M" if granularity == "hourly" else "%d/%m/%Y"
                )
                st.dataframe(displayed.rename(columns={
                    metric: _label(metric, language) for metric in selected_metrics
                }), width="stretch", hide_index=True, height=400)
                st.download_button(
                    text("Baixar médias em CSV", "Descargar promedios CSV"),
                    data=_csv(summary), file_name=f"ons_termicas_medias_{granularity}.csv",
                    mime="text/csv", key="thermal_summary_csv",
                )
            else:
                max_preview = 5000
                st.caption(text(
                    f"Mostrando até {max_preview} registros na tela; o CSV contém todas as linhas filtradas.",
                    f"Mostrando hasta {max_preview} registros; el CSV contiene todas las filas filtradas.",
                ))
                st.dataframe(base.head(max_preview), width="stretch", hide_index=True, height=450)
                # Evita serialização de centenas de MB sem um intervalo reduzido.
                if len(base) <= 250_000:
                    st.download_button(
                        text("Baixar dados originais (todas as colunas)", "Descargar datos originales (todas las columnas)"),
                        data=_csv(base), file_name="ons_termicas_registros_filtrados.csv",
                        mime="text/csv", key="thermal_raw_csv",
                    )
                else:
                    st.download_button(
                        text("Baixar dados originais completos (CSV.GZ)", "Descargar datos originales completos (CSV.GZ)"),
                        data=_csv_gzip(base),
                        file_name="ons_termicas_registros_filtrados.csv.gz",
                        mime="application/gzip",
                        key="thermal_raw_gzip",
                    )
                    st.caption(text(
                        "Arquivo CSV comprimido (gzip), sem limite de 250 mil linhas.",
                        "Archivo CSV comprimido (gzip), sin límite de 250 mil filas.",
                    ))

        if not result.file_report.empty:
            with st.expander(text("Arquivos térmicos processados", "Archivos térmicos procesados")):
                st.dataframe(result.file_report, width="stretch", hide_index=True)
