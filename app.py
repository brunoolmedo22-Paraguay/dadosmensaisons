from __future__ import annotations

import base64
import importlib
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

import pandas as pd
import streamlit as st

import balanco_ons as _balanco
import ear_download as _ear_download
import ear_processing as _ear
import ena_download as _ena_download
import ena_processing as _ena
import ons_download as _balance_download
import unified_ons as _unified

# Evita módulos auxiliares antigos na memória durante um redeploy do Streamlit.
_balanco = importlib.reload(_balanco)
_ear_download = importlib.reload(_ear_download)
_ear = importlib.reload(_ear)
_ena_download = importlib.reload(_ena_download)
_ena = importlib.reload(_ena)
_balance_download = importlib.reload(_balance_download)
_unified = importlib.reload(_unified)

Granularity = _unified.Granularity
DataSource = _unified.DataSource

FIRST_AVAILABLE_YEAR = 2000
CURRENT_YEAR = date.today().year
HERO_LOGO_PATH = Path(__file__).parent / "assets" / "logo_contorno_transparente.svg"
HERO_LOGO_DATA_URI = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(HERO_LOGO_PATH.read_bytes()).decode("ascii")
    if HERO_LOGO_PATH.exists()
    else ""
)

GRANULARITIES: tuple[Granularity, ...] = ("daily", "monthly", "yearly")
GRANULARITY_LABELS: dict[str, dict[Granularity, str]] = {
    "PT": {"daily": "Diária", "monthly": "Mensal", "yearly": "Anual"},
    "ES": {"daily": "Diaria", "monthly": "Mensual", "yearly": "Anual"},
}
GRANULARITY_TITLES: dict[str, dict[Granularity, str]] = {
    "PT": {
        "daily": "Dados diários — {subsystem}",
        "monthly": "Médias mensais — {subsystem}",
        "yearly": "Médias anuais — {subsystem}",
    },
    "ES": {
        "daily": "Datos diarios — {subsystem}",
        "monthly": "Promedios mensuales — {subsystem}",
        "yearly": "Promedios anuales — {subsystem}",
    },
}
CHART_TITLES: dict[str, dict[Granularity, str]] = {
    "PT": {"daily": "Evolução diária", "monthly": "Evolução mensal", "yearly": "Evolução anual"},
    "ES": {"daily": "Evolución diaria", "monthly": "Evolución mensual", "yearly": "Evolución anual"},
}
GRANULARITY_SLUGS: dict[Granularity, str] = {
    "daily": "diario",
    "monthly": "mensal",
    "yearly": "anual",
}
SOURCE_LABELS: dict[str, dict[DataSource, str]] = {
    "PT": {"BALANCO": "Balanço", "EAR": "EAR", "ENA": "ENA"},
    "ES": {"BALANCO": "Balance", "EAR": "EAR", "ENA": "ENA"},
}

UI_TEXT: dict[str, dict[str, str]] = {
    "PT": {
        "hero_kicker": "ONS · Consolidação histórica",
        "hero_title": "Dados Históricos do SIN",
        "hero_copy": (
            "Consulte em uma única plataforma o Balanço Energético por Subsistema, "
            "a Energia Armazenada (EAR) e a Energia Natural Afluente (ENA), "
            "com saída diária, mensal ou anual."
        ),
        "empty_title": "Os resultados aparecerão aqui",
        "empty_copy": (
            "Defina o período acima e clique em <strong>Baixar dados do ONS</strong> "
            "para iniciar a análise."
        ),
        "progress_catalog": "Consultando as bases oficiais do ONS...",
        "progress_file": "{source}: arquivo de {year} concluído ({completed}/{total})...",
        "progress_validate": "{source}: validando e consolidando os dados...",
        "progress_done": "Processamento concluído.",
        "auto_kicker": "Obtenção automática",
        "select_period": "Selecione o período",
        "select_period_copy": "Escolha o primeiro e o último ano. Os dois extremos serão incluídos.",
        "year_range": "Ano inicial e ano final",
        "download_ons": "Baixar dados do ONS",
        "source_note": "Fontes oficiais do ONS · Formato Parquet · Processamento temporário",
        "flow_kicker": "Fluxo da plataforma",
        "flow_title": "O que será feito?",
        "flow_lead": (
            "Ao clicar no botão, a plataforma obterá as três bases para o período "
            "<strong>{start_year}–{end_year}</strong>."
        ),
        "step_1_title": "Localizar as três bases",
        "step_1_copy": "Consulta os catálogos oficiais de Balanço Energético, EAR e ENA.",
        "step_2_title": "Baixar e validar",
        "step_2_copy": "Salva temporariamente os Parquets anuais e verifica o conteúdo.",
        "step_3_title": "Consolidar por período",
        "step_3_copy": "Prepara uma única tabela e um único CSV diário, mensal ou anual.",
        "unexpected_error": "Ocorreu um erro inesperado em {source}: {error}",
        "stale_results": (
            "Os resultados exibidos ainda correspondem a **{start}–{end}**. "
            "Clique em **{button}** para processar o novo intervalo selecionado."
        ),
        "no_result": "Nenhuma das bases pôde gerar resultados para o período selecionado.",
        "processed_success": (
            "Dados de **{start}–{end}** processados: {files} arquivo(s) Parquet, "
            "{megabytes:.1f} MB."
        ),
        "source_kicker": "Conteúdo da saída",
        "source_title": "Selecione as bases que deseja visualizar",
        "source_copy": "Marque uma, duas ou as três opções. A tabela, o gráfico e o CSV serão atualizados juntos.",
        "source_selector": "Bases de dados",
        "select_one_source": "Selecione ao menos uma base de dados.",
        "source_unavailable": "A base {source} não foi carregada. Baixe novamente o período para incluí-la.",
        "output_kicker": "Configuração da saída",
        "output_title": "Subsistema, discretização e CSV",
        "subsystem_selector": "Subsistema",
        "granularity_selector": "Discretização dos dados",
        "no_subsystems": "Nenhum subsistema foi encontrado nas bases selecionadas.",
        "start_date": "Data inicial",
        "end_date": "Data final",
        "invalid_dates": "A data inicial deve ser anterior à data final.",
        "calendar_note": "Use os dois calendários para limitar o volume exibido e exportado.",
        "full_interval": "Todo o intervalo baixado, de {start} a {end}, será incluído.",
        "no_data_config": "Não há dados para a configuração selecionada.",
        "download_csv": "Baixar dados consolidados em CSV",
        "csv_note": "O CSV contém os dados consolidados, sem as colunas auxiliares de cobertura e status.",
        "summary_kicker": "Resumo da saída",
        "discretization": "Discretização",
        "result_rows": "Linhas no resultado",
        "complete_periods": "Períodos completos",
        "average_coverage": "Cobertura média",
        "period_shown": "Período exibido: {start} a {end}.",
        "values_note": "Balanço em MWmed; EAR em MWmês e percentual; ENA em MWmed e % da MLT.",
        "sin_ena_calculated_label": "SIN · ENA calculada",
        "sin_ena_calculation_note": (
            "**ENA do SIN calculada.** A base diária de ENA não fornece uma série própria "
            "para o SIN. A plataforma só calcula o valor quando SE/CO, Sul, Nordeste e "
            "Norte estão presentes no mesmo dia. Para cada subsistema: "
            r"$MLT_i = ENA_i / (\%MLT_i/100)$; depois: "
            r"$\%MLT_{SIN} = 100\,\sum_i ENA_i / \sum_i MLT_i$. "
            "Se faltar qualquer um dos quatro subsistemas, o SIN não é calculado."
        ),
        "adjust_config": "Ajuste a configuração ao lado para visualizar os dados.",
        "chart_empty": "O gráfico será exibido quando houver dados na tabela.",
        "metric_selector": "Grandeza",
        "x_month_year": "Mês e ano",
        "x_date": "Data",
        "x_year": "Ano",
        "processed_files": "Arquivos processados",
        "base_column": "Base",
    },
    "ES": {
        "hero_kicker": "ONS · Consolidación histórica",
        "hero_title": "Datos Históricos del SIN",
        "hero_copy": (
            "Consulte en una única plataforma el Balance Energético por Subsistema, "
            "la Energía Almacenada (EAR) y la Energía Natural Afluente (ENA), "
            "con salida diaria, mensual o anual."
        ),
        "empty_title": "Los resultados aparecerán aquí",
        "empty_copy": (
            "Defina el período anterior y pulse <strong>Descargar datos del ONS</strong> "
            "para iniciar el análisis."
        ),
        "progress_catalog": "Consultando las bases oficiales del ONS...",
        "progress_file": "{source}: archivo de {year} completado ({completed}/{total})...",
        "progress_validate": "{source}: validando y consolidando los datos...",
        "progress_done": "Procesamiento finalizado.",
        "auto_kicker": "Obtención automática",
        "select_period": "Seleccione el período",
        "select_period_copy": "Seleccione el primer y el último año. Ambos extremos serán incluidos.",
        "year_range": "Año inicial y año final",
        "download_ons": "Descargar datos del ONS",
        "source_note": "Fuentes oficiales del ONS · Formato Parquet · Procesamiento temporal",
        "flow_kicker": "Flujo de la plataforma",
        "flow_title": "¿Qué se hará?",
        "flow_lead": (
            "Al pulsar el botón, la plataforma obtendrá las tres bases para el período "
            "<strong>{start_year}–{end_year}</strong>."
        ),
        "step_1_title": "Localizar las tres bases",
        "step_1_copy": "Consulta los catálogos oficiales de Balance Energético, EAR y ENA.",
        "step_2_title": "Descargar y validar",
        "step_2_copy": "Guarda temporalmente los Parquet anuales y verifica el contenido.",
        "step_3_title": "Consolidar por período",
        "step_3_copy": "Prepara una única tabla y un único CSV diario, mensual o anual.",
        "unexpected_error": "Se produjo un error inesperado en {source}: {error}",
        "stale_results": (
            "Los resultados mostrados todavía corresponden a **{start}–{end}**. "
            "Pulse **{button}** para procesar el nuevo intervalo seleccionado."
        ),
        "no_result": "Ninguna de las bases pudo generar resultados para el período seleccionado.",
        "processed_success": (
            "Datos de **{start}–{end}** procesados: {files} archivo(s) Parquet, "
            "{megabytes:.1f} MB."
        ),
        "source_kicker": "Contenido de la salida",
        "source_title": "Seleccione las bases que desea visualizar",
        "source_copy": "Marque una, dos o las tres opciones. La tabla, el gráfico y el CSV se actualizarán juntos.",
        "source_selector": "Bases de datos",
        "select_one_source": "Seleccione al menos una base de datos.",
        "source_unavailable": "La base {source} no fue cargada. Descargue nuevamente el período para incluirla.",
        "output_kicker": "Configuración de salida",
        "output_title": "Subsistema, discretización y CSV",
        "subsystem_selector": "Subsistema",
        "granularity_selector": "Discretización de los datos",
        "no_subsystems": "No se encontraron subsistemas en las bases seleccionadas.",
        "start_date": "Fecha inicial",
        "end_date": "Fecha final",
        "invalid_dates": "La fecha inicial debe ser anterior a la fecha final.",
        "calendar_note": "Use los dos calendarios para limitar el volumen mostrado y exportado.",
        "full_interval": "Se incluirá todo el intervalo descargado, de {start} a {end}.",
        "no_data_config": "No hay datos para la configuración seleccionada.",
        "download_csv": "Descargar datos consolidados en CSV",
        "csv_note": "El CSV contiene los datos consolidados, sin las columnas auxiliares de cobertura y estado.",
        "summary_kicker": "Resumen de salida",
        "discretization": "Discretización",
        "result_rows": "Filas en el resultado",
        "complete_periods": "Períodos completos",
        "average_coverage": "Cobertura promedio",
        "period_shown": "Período mostrado: {start} a {end}.",
        "values_note": "Balance en MWmed; EAR en MWmes y porcentaje; ENA en MWmed y % de la MLT.",
        "sin_ena_calculated_label": "SIN · ENA calculada",
        "sin_ena_calculation_note": (
            "**ENA del SIN calculada.** La base diaria de ENA no suministra una serie propia "
            "para el SIN. La plataforma solo calcula el valor cuando SE/CO, Sur, Nordeste y "
            "Norte están presentes el mismo día. Para cada subsistema: "
            r"$MLT_i = ENA_i / (\%MLT_i/100)$; después: "
            r"$\%MLT_{SIN} = 100\,\sum_i ENA_i / \sum_i MLT_i$. "
            "Si falta cualquiera de los cuatro subsistemas, el SIN no se calcula."
        ),
        "adjust_config": "Ajuste la configuración de la derecha para visualizar los datos.",
        "chart_empty": "El gráfico se mostrará cuando haya datos en la tabla.",
        "metric_selector": "Magnitud",
        "x_month_year": "Mes y año",
        "x_date": "Fecha",
        "x_year": "Año",
        "processed_files": "Archivos procesados",
        "base_column": "Base",
    },
}

VALID_UI_LANGUAGES = ("PT", "ES")


def ui_text(key: str) -> str:
    language = st.session_state.get("ui_language", "PT")
    if language not in VALID_UI_LANGUAGES:
        language = "PT"
    return UI_TEXT[language][key]

st.set_page_config(
    page_title="SIN · ONS",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        :root {
            --ink: var(--text-color);
            --muted: color-mix(in srgb, var(--text-color) 68%, transparent);
            --brand: #006b70;
            --brand-dark: #004e52;
            --brand-readable: color-mix(in srgb, var(--brand) 72%, var(--text-color));
            --accent: #e2ad21;
            --surface: var(--secondary-background-color);
            --line: color-mix(in srgb, var(--text-color) 16%, transparent);
            --soft-shadow: color-mix(in srgb, #143d40 16%, transparent);
        }
        .stApp {
            background:
                radial-gradient(circle at 90% -10%, rgba(0, 107, 112, .12), transparent 31rem),
                var(--background-color);
        }
        [data-testid="stSidebar"] {
            border-right: 1px solid var(--line);
        }
        .hero {
            padding: 1.65rem 1.8rem;
            border-radius: 20px;
            color: white;
            background:
                linear-gradient(120deg, rgba(0, 78, 82, .97), rgba(0, 107, 112, .90)),
                linear-gradient(90deg, #004e52, #006b70);
            box-shadow: 0 12px 30px rgba(12, 71, 75, .13);
            margin-bottom: 1.25rem;
            overflow: hidden;
        }
        .hero-layout {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(14rem, 27rem);
            gap: 1.5rem;
            align-items: center;
        }
        .hero-text {
            min-width: 0;
        }
        .hero-logo {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 9rem;
        }
        .hero-logo img {
            display: block;
            width: min(100%, 24rem);
            height: auto;
            max-height: 12rem;
        }
        .hero-kicker {
            color: #c8ebea;
            font-size: .76rem;
            font-weight: 700;
            letter-spacing: .12em;
            text-transform: uppercase;
            margin-bottom: .35rem;
        }
        .hero-title {
            font-size: clamp(1.8rem, 4vw, 2.65rem);
            font-weight: 760;
            letter-spacing: -.035em;
            line-height: 1.08;
            margin: 0;
        }
        .hero-copy {
            color: #e8f6f5;
            font-size: 1rem;
            max-width: 54rem;
            margin: .7rem 0 0;
        }
        @media (max-width: 820px) {
            .hero-layout {
                grid-template-columns: 1fr;
            }
            .hero-logo {
                min-height: auto;
                padding-top: .35rem;
            }
            .hero-logo img {
                width: min(72%, 18rem);
                max-height: 9rem;
            }
        }
        .empty-card {
            background: var(--surface);
            border: none;
            border-radius: 16px;
            min-height: 9.2rem;
            padding: 1.25rem;
            box-shadow: 0 4px 16px var(--soft-shadow);
        }
        .step-number {
            display: inline-grid;
            place-items: center;
            width: 1.8rem;
            height: 1.8rem;
            color: white;
            background: var(--brand);
            border-radius: 50%;
            font-weight: 700;
            margin-bottom: .7rem;
        }
        .empty-card h3 {
            color: var(--ink);
            font-size: 1rem;
            margin: 0 0 .35rem;
        }
        .empty-card p {
            color: var(--muted);
            font-size: .9rem;
            margin: 0;
        }
        [data-testid="stMetric"] {
            background: var(--surface);
            border: none;
            border-radius: 14px;
            padding: .85rem 1rem;
        }
        div[data-testid="stDownloadButton"] button {
            background: var(--brand);
            border: 1px solid var(--brand);
            color: white;
            font-weight: 650;
        }
        div[data-testid="stDownloadButton"] button:hover {
            background: var(--brand-dark);
            border-color: var(--brand-dark);
            color: white;
        }
        .small-note {
            color: var(--muted);
            font-size: .83rem;
        }
        .panel-kicker {
            color: var(--brand-readable);
            font-size: .72rem;
            font-weight: 750;
            letter-spacing: .11em;
            text-transform: uppercase;
            margin-bottom: .2rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border: none !important;
        }
        .st-key-download_panel {
            background: var(--surface);
            border: none !important;
            border-radius: 18px;
            min-height: 20.25rem;
            padding: 1.15rem 1.25rem;
            box-shadow: none;
        }
        /* Mantém o seletor Balanço/EAR/ENA alinhado à identidade visual do título. */
        .st-key-source_selection_panel button[aria-pressed="true"] {
            background: var(--brand) !important;
            border-color: var(--brand) !important;
            color: white !important;
        }
        .st-key-source_selection_panel button[aria-pressed="true"]:hover {
            background: var(--brand-dark) !important;
            border-color: var(--brand-dark) !important;
            color: white !important;
        }
        .st-key-source_selection_panel button[aria-pressed="true"] p,
        .st-key-source_selection_panel button[aria-pressed="true"] span {
            color: white !important;
        }
        .st-key-output_panel {
            background: var(--surface);
            border: none !important;
            border-radius: 18px;
            padding: 1.05rem 1.15rem;
            box-shadow: none;
        }
        .st-key-output_kpis {
            background: var(--surface);
            border: none !important;
            border-radius: 18px;
            padding: .9rem 1rem 1rem;
            box-shadow: none;
        }
        .st-key-output_kpis [data-testid="stMetric"] {
            min-height: 5rem;
            padding: .65rem .75rem;
            background: color-mix(
                in srgb,
                var(--secondary-background-color) 82%,
                var(--background-color)
            );
            border: none;
            border-radius: 12px;
        }
        .st-key-output_kpis [data-testid="stMetricLabel"] p {
            color: var(--muted);
            font-size: .75rem;
            line-height: 1.2;
        }
        .st-key-output_kpis [data-testid="stMetricValue"] {
            color: var(--ink);
            font-size: 1.45rem;
            line-height: 1.15;
        }
        .st-key-results_panel {
            background: var(--surface);
            border: none !important;
            border-radius: 18px;
            padding: 1.1rem 1.15rem 1.2rem;
            box-shadow: 0 8px 24px var(--soft-shadow);
            margin-top: .35rem;
        }
        .process-card {
            min-height: 20.25rem;
            padding: 1.35rem 1.45rem;
            border: none;
            border-radius: 18px;
            background: linear-gradient(
                145deg,
                color-mix(in srgb, var(--brand) 10%, var(--secondary-background-color)),
                var(--secondary-background-color)
            );
            box-shadow: none;
        }
        .process-card h2 {
            color: var(--ink);
            font-size: 1.35rem;
            letter-spacing: -.02em;
            margin: .1rem 0 .35rem;
        }
        .process-lead {
            color: var(--muted);
            font-size: .9rem;
            margin: 0 0 1rem;
        }
        .process-step {
            display: grid;
            grid-template-columns: 2rem 1fr;
            gap: .7rem;
            align-items: start;
            margin-top: .8rem;
        }
        .process-number {
            display: grid;
            place-items: center;
            width: 1.85rem;
            height: 1.85rem;
            color: white;
            background: var(--brand);
            border-radius: 50%;
            font-size: .78rem;
            font-weight: 750;
        }
        .process-step strong {
            display: block;
            color: var(--ink);
            font-size: .9rem;
            margin-bottom: .08rem;
        }
        .process-step p {
            color: var(--muted);
            font-size: .82rem;
            line-height: 1.35;
            margin: 0;
        }
        .result-placeholder {
            margin-top: 1.25rem;
            padding: 1.7rem;
            color: var(--muted);
            text-align: center;
            border: none;
            border-radius: 16px;
            background: color-mix(
                in srgb,
                var(--secondary-background-color) 72%,
                transparent
            );
        }
        .result-placeholder h3 {
            color: var(--ink);
            font-size: 1rem;
            margin: 0 0 .25rem;
        }
        .result-placeholder p {
            font-size: .88rem;
            margin: 0;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


if st.session_state.get("ui_language") not in VALID_UI_LANGUAGES:
    st.session_state["ui_language"] = "PT"
if st.session_state.get("ui_language_selector") not in VALID_UI_LANGUAGES:
    st.session_state["ui_language_selector"] = st.session_state["ui_language"]


def keep_language_selected() -> None:
    selected = st.session_state.get("ui_language_selector")
    if selected in VALID_UI_LANGUAGES:
        st.session_state["ui_language"] = selected
    else:
        st.session_state["ui_language_selector"] = st.session_state["ui_language"]


language_spacer, language_column = st.columns([8, 1], gap="small")
with language_column:
    st.segmented_control(
        "Idioma",
        options=VALID_UI_LANGUAGES,
        key="ui_language_selector",
        on_change=keep_language_selected,
        label_visibility="collapsed",
        width="stretch",
    )

language = st.session_state["ui_language"]


def subsystem_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")
    return slug or "subsistema"


def csv_bytes(data: pd.DataFrame) -> bytes:
    return _unified.build_unified_csv_export(data).to_csv(
        index=False,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
    ).encode("utf-8-sig")


def display_table(data: pd.DataFrame, metrics: Sequence[str]) -> None:
    visible = data.drop(columns=["Mês nº", "__period_start"], errors="ignore")
    config: dict[str, Any] = {
        "Ano": st.column_config.NumberColumn(format="%d"),
        "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Cobertura Balanço (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Cobertura EAR (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Cobertura ENA (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Horas com dados": st.column_config.NumberColumn(format="%d"),
        "Horas esperadas": st.column_config.NumberColumn(format="%d"),
        "Dias com dados": st.column_config.NumberColumn(format="%d"),
        "Dias esperados": st.column_config.NumberColumn(format="%d"),
        "Dias com dados ENA": st.column_config.NumberColumn(format="%d"),
        "Dias esperados ENA": st.column_config.NumberColumn(format="%d"),
    }
    config.update(
        {metric: st.column_config.NumberColumn(format="%.2f") for metric in metrics}
    )
    st.dataframe(
        visible,
        width="stretch",
        hide_index=True,
        column_config=config,
        height=min(620, 96 + 35 * len(visible)),
    )


def render_empty_state() -> None:
    st.markdown(
        f"""
        <section class="result-placeholder">
            <h3>{ui_text("empty_title")}</h3>
            <p>{ui_text("empty_copy")}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def obtain_ons_data(
    start_year: int,
    end_year: int,
) -> tuple[dict[DataSource, Any], int, list[str]]:
    years = list(range(start_year, end_year + 1))
    progress = st.progress(2, text=ui_text("progress_catalog"))
    results: dict[DataSource, Any] = {}
    total_bytes = 0
    source_errors: list[str] = []

    source_specs = (
        (
            "BALANCO",
            SOURCE_LABELS[language]["BALANCO"],
            _balance_download.download_parquet_years,
            _balanco.process_parquet_files,
            "balanco",
        ),
        (
            "EAR",
            SOURCE_LABELS[language]["EAR"],
            _ear_download.download_parquet_years,
            _ear.process_parquet_files,
            "ear",
        ),
        (
            "ENA",
            SOURCE_LABELS[language]["ENA"],
            _ena_download.download_parquet_years,
            _ena.process_parquet_files,
            "ena",
        ),
    )
    total_steps = len(years) * len(source_specs)

    try:
        with TemporaryDirectory(prefix="ons_unificado_") as temporary_directory:
            temporary_root = Path(temporary_directory)
            for source_index, (
                source_key,
                source_label,
                downloader,
                processor,
                folder_name,
            ) in enumerate(source_specs):
                def update_progress(
                    completed: int,
                    total: int,
                    year: int,
                    *,
                    offset: int = source_index * len(years),
                    label: str = source_label,
                ) -> None:
                    overall_completed = offset + completed
                    percentage = 5 + int(75 * overall_completed / max(total_steps, 1))
                    progress.progress(
                        percentage,
                        text=ui_text("progress_file").format(
                            source=label,
                            year=year,
                            completed=completed,
                            total=total,
                        ),
                    )

                try:
                    batch = downloader(
                        years=years,
                        destination=temporary_root / folder_name,
                        progress_callback=update_progress,
                    )
                    progress.progress(
                        82 + source_index * 7,
                        text=ui_text("progress_validate").format(source=source_label),
                    )
                    result = processor(batch.files)
                    result.errors = [*batch.errors, *result.errors]
                    results[source_key] = result
                    total_bytes += batch.total_bytes
                except Exception as exc:
                    source_errors.append(
                        ui_text("unexpected_error").format(
                            source=source_label,
                            error=exc,
                        )
                    )
            progress.progress(100, text=ui_text("progress_done"))
            return results, total_bytes, source_errors
    finally:
        progress.empty()


def result_has_data(source: DataSource, result: Any) -> bool:
    if result is None:
        return False
    if source == "BALANCO":
        return not result.hourly.empty
    return not result.daily.empty


def available_sources(results: dict[DataSource, Any]) -> list[DataSource]:
    return [source for source in _unified.DATA_SOURCES if result_has_data(source, results.get(source))]


def unified_subsystems(
    results: dict[DataSource, Any],
    selected_sources: Sequence[DataSource],
) -> list[tuple[str, str]]:
    labels: dict[str, str] = {}
    if "BALANCO" in selected_sources and result_has_data("BALANCO", results.get("BALANCO")):
        labels.update(dict(_balanco.available_subsystems(results["BALANCO"].hourly)))
    if "EAR" in selected_sources and result_has_data("EAR", results.get("EAR")):
        for key, label in _ear.available_subsystems(results["EAR"].daily):
            labels.setdefault(key, label)
    if "ENA" in selected_sources and result_has_data("ENA", results.get("ENA")):
        for key, label in _ena.available_subsystems(results["ENA"].daily):
            labels.setdefault(key, label)
        if ena_has_calculated_sin(results):
            labels["SIN"] = ui_text("sin_ena_calculated_label")
    order = {"SIN": 0, "SE": 1, "S": 2, "NE": 3, "N": 4}
    return sorted(labels.items(), key=lambda item: (order.get(item[0], 99), item[1].casefold()))


def ena_has_calculated_sin(results: dict[DataSource, Any]) -> bool:
    result = results.get("ENA")
    if not result_has_data("ENA", result):
        return False
    daily = result.daily
    if "__sin_calculated" not in daily.columns:
        return False
    calculated = daily["__sin_calculated"].fillna(False).astype(bool)
    return bool((daily["__subsystem_key"].eq("SIN") & calculated).any())


st.markdown(
    f"""
    <section class="hero">
        <div class="hero-layout">
            <div class="hero-text">
                <div class="hero-kicker">{ui_text("hero_kicker")}</div>
                <h1 class="hero-title">{ui_text("hero_title")}</h1>
                <p class="hero-copy">{ui_text("hero_copy")}</p>
            </div>
            <div class="hero-logo" aria-hidden="true">
                <img src="{HERO_LOGO_DATA_URI}" alt="" />
            </div>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

default_start = max(FIRST_AVAILABLE_YEAR, CURRENT_YEAR - 4)
with st.container(border=True, key="download_panel"):
    st.markdown(
        f'<div class="panel-kicker">{ui_text("auto_kicker")}</div>',
        unsafe_allow_html=True,
    )
    left_column, right_column = st.columns([1.15, 1], gap="large")

    with left_column:
        st.subheader(ui_text("select_period"))
        st.caption(ui_text("select_period_copy"))
        selected_period = st.select_slider(
            ui_text("year_range"),
            options=list(range(FIRST_AVAILABLE_YEAR, CURRENT_YEAR + 1)),
            value=(default_start, CURRENT_YEAR),
        )
        download_clicked = st.button(
            ui_text("download_ons"),
            type="primary",
            width="stretch",
        )
        st.caption(ui_text("source_note"))

    start_year, end_year = (int(value) for value in selected_period)

    with right_column:
        st.markdown(
            f"""
            <section class="process-card">
                <div class="panel-kicker">{ui_text("flow_kicker")}</div>
                <h2>{ui_text("flow_title")}</h2>
                <p class="process-lead">
                    {ui_text("flow_lead").format(start_year=start_year, end_year=end_year)}
                </p>
                <div class="process-step">
                    <div class="process-number">1</div>
                    <div><strong>{ui_text("step_1_title")}</strong><p>{ui_text("step_1_copy")}</p></div>
                </div>
                <div class="process-step">
                    <div class="process-number">2</div>
                    <div><strong>{ui_text("step_2_title")}</strong><p>{ui_text("step_2_copy")}</p></div>
                </div>
                <div class="process-step">
                    <div class="process-number">3</div>
                    <div><strong>{ui_text("step_3_title")}</strong><p>{ui_text("step_3_copy")}</p></div>
                </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

# O seletor fica exatamente entre o painel de período e o painel da tabela.
if not isinstance(st.session_state.get("selected_data_sources"), (list, tuple)):
    st.session_state["selected_data_sources"] = list(_unified.DATA_SOURCES)
with st.container(border=True, key="source_selection_panel"):
    source_text_column, source_control_column = st.columns([1.25, 1], gap="large")
    with source_text_column:
        st.markdown(
            f'<div class="panel-kicker">{ui_text("source_kicker")}</div>',
            unsafe_allow_html=True,
        )
        st.subheader(ui_text("source_title"))
        st.caption(ui_text("source_copy"))
    with source_control_column:
        st.segmented_control(
            ui_text("source_selector"),
            options=list(_unified.DATA_SOURCES),
            selection_mode="multi",
            key="selected_data_sources",
            format_func=lambda value: SOURCE_LABELS[language][value],
            width="stretch",
        )

selected_sources = [
    source
    for source in _unified.DATA_SOURCES
    if source in (st.session_state.get("selected_data_sources") or [])
]

if download_clicked:
    for state_key in [
        "ons_results",
        "ons_period",
        "ons_download_bytes",
        "ons_source_errors",
        "subsystem_value",
    ]:
        st.session_state.pop(state_key, None)
    for state_key in list(st.session_state):
        if str(state_key).startswith(("analysis_start_", "analysis_end_")):
            st.session_state.pop(state_key, None)

    downloaded_results, downloaded_bytes, source_errors = obtain_ons_data(
        start_year=start_year,
        end_year=end_year,
    )
    st.session_state["ons_results"] = downloaded_results
    st.session_state["ons_period"] = (start_year, end_year)
    st.session_state["ons_download_bytes"] = downloaded_bytes
    st.session_state["ons_source_errors"] = source_errors

results: dict[DataSource, Any] | None = st.session_state.get("ons_results")
loaded_period = st.session_state.get("ons_period")

for message in st.session_state.get("ons_source_errors", []):
    st.error(message)

if results is None:
    render_empty_state()
    st.stop()

if loaded_period != (start_year, end_year):
    loaded_start, loaded_end = loaded_period
    st.info(
        ui_text("stale_results").format(
            start=loaded_start,
            end=loaded_end,
            button=ui_text("download_ons"),
        )
    )

for source, source_result in results.items():
    source_label = SOURCE_LABELS[language][source]
    for message in source_result.errors:
        st.error(f"{source_label}: {message}")
    for message in source_result.warnings:
        st.warning(f"{source_label}: {message}")

loaded_sources = available_sources(results)
if not loaded_sources:
    st.error(ui_text("no_result"))
    st.stop()

if not selected_sources:
    st.warning(ui_text("select_one_source"))
    st.stop()

usable_sources = [source for source in selected_sources if source in loaded_sources]
for source in selected_sources:
    if source not in loaded_sources:
        st.warning(
            ui_text("source_unavailable").format(
                source=SOURCE_LABELS[language][source]
            )
        )
if not usable_sources:
    st.stop()

downloaded_files = sum(len(results[source].file_report) for source in loaded_sources)
downloaded_megabytes = float(st.session_state.get("ons_download_bytes", 0)) / (1024 * 1024)
st.success(
    ui_text("processed_success").format(
        start=loaded_period[0],
        end=loaded_period[1],
        files=downloaded_files,
        megabytes=downloaded_megabytes,
    )
)

subsystem_items = unified_subsystems(results, usable_sources)
if not subsystem_items:
    st.error(ui_text("no_subsystems"))
    st.stop()
subsystem_labels = dict(subsystem_items)
subsystem_keys = [key for key, _ in subsystem_items]
if st.session_state.get("subsystem_value") not in subsystem_keys:
    st.session_state.pop("subsystem_value", None)

with st.container(border=True, key="results_panel"):
    table_column, settings_column = st.columns([1.7, 1], gap="large")

    with settings_column:
        with st.container(border=True, key="output_panel"):
            st.markdown(
                f'<div class="panel-kicker">{ui_text("output_kicker")}</div>',
                unsafe_allow_html=True,
            )
            st.subheader(ui_text("output_title"))
            subsystem_key = st.selectbox(
                ui_text("subsystem_selector"),
                options=subsystem_keys,
                index=subsystem_keys.index("SIN") if "SIN" in subsystem_keys else 0,
                key="subsystem_value",
                format_func=lambda value: subsystem_labels[value],
            )
            selected_subsystem_label = subsystem_labels[subsystem_key]
            if (
                subsystem_key == "SIN"
                and "ENA" in usable_sources
                and ena_has_calculated_sin(results)
            ):
                st.info(ui_text("sin_ena_calculation_note"))

            balance_data = pd.DataFrame()
            ear_data = pd.DataFrame()
            ena_data = pd.DataFrame()
            if "BALANCO" in usable_sources:
                balance_data = _balanco.filter_hourly_by_subsystem(
                    results["BALANCO"].hourly,
                    subsystem_key,
                )
            if "EAR" in usable_sources:
                ear_data = _ear.filter_daily_by_subsystem(
                    results["EAR"].daily,
                    subsystem_key,
                )
            if "ENA" in usable_sources:
                ena_data = _ena.filter_daily_by_subsystem(
                    results["ENA"].daily,
                    subsystem_key,
                )

            bounds = _unified.source_date_bounds(
                balance_data,
                ear_data,
                usable_sources,
                ena_data=ena_data,
            )
            if bounds is None:
                st.warning(ui_text("no_data_config"))
                st.stop()
            data_min, data_max = bounds

            granularity = st.selectbox(
                ui_text("granularity_selector"),
                options=GRANULARITIES,
                index=1,
                key="granularity_value",
                format_func=lambda value: GRANULARITY_LABELS[language][value],
            )
            granularity_label = GRANULARITY_LABELS[language][granularity]

            analysis_start: date | None = None
            analysis_end: date | None = None
            valid_dates = True

            if granularity == "daily":
                suggested_start = max(data_min, data_max - timedelta(days=30))
                source_slug = "_".join(source.lower() for source in usable_sources)
                date_key = (
                    f"{loaded_period[0]}_{loaded_period[1]}_"
                    f"{subsystem_slug(subsystem_key)}_{source_slug}_{granularity}"
                )
                start_column, end_column = st.columns(2, gap="small")
                with start_column:
                    analysis_start = st.date_input(
                        ui_text("start_date"),
                        value=suggested_start,
                        min_value=data_min,
                        max_value=data_max,
                        key=f"analysis_start_{date_key}",
                    )
                with end_column:
                    analysis_end = st.date_input(
                        ui_text("end_date"),
                        value=data_max,
                        min_value=data_min,
                        max_value=data_max,
                        key=f"analysis_end_{date_key}",
                    )
                if analysis_start > analysis_end:
                    st.error(ui_text("invalid_dates"))
                    valid_dates = False
                else:
                    st.caption(ui_text("calendar_note"))
            else:
                st.info(
                    ui_text("full_interval").format(
                        start=loaded_period[0], end=loaded_period[1]
                    )
                )

            if valid_dates:
                balance_summary = (
                    _balanco.build_period_summary(
                        balance_data,
                        granularity=granularity,
                        start_date=analysis_start,
                        end_date=analysis_end,
                    )
                    if "BALANCO" in usable_sources
                    else pd.DataFrame()
                )
                ear_summary = (
                    _ear.build_period_summary(
                        ear_data,
                        granularity=granularity,
                        start_date=analysis_start,
                        end_date=analysis_end,
                    )
                    if "EAR" in usable_sources
                    else pd.DataFrame()
                )
                ena_summary = (
                    _ena.build_period_summary(
                        ena_data,
                        granularity=granularity,
                        start_date=analysis_start,
                        end_date=analysis_end,
                    )
                    if "ENA" in usable_sources
                    else pd.DataFrame()
                )
                summary, visible_metric_columns, coverage_columns, status_columns = (
                    _unified.combine_summaries(
                        balance_summary=balance_summary,
                        ear_summary=ear_summary,
                        ena_summary=ena_summary,
                        granularity=granularity,
                        selected_sources=usable_sources,
                        balance_metrics=(
                            results["BALANCO"].metric_columns
                            if "BALANCO" in usable_sources
                            else ()
                        ),
                        ear_metrics=(
                            results["EAR"].metric_columns
                            if "EAR" in usable_sources
                            else ()
                        ),
                        ena_metrics=(
                            results["ENA"].metric_columns
                            if "ENA" in usable_sources
                            else ()
                        ),
                    )
                )
            else:
                summary = pd.DataFrame()
                visible_metric_columns = []
                coverage_columns = []
                status_columns = []

            st.divider()
            if summary.empty:
                st.warning(ui_text("no_data_config"))

            if analysis_start is not None and analysis_end is not None:
                export_period = f"{analysis_start:%Y%m%d}-{analysis_end:%Y%m%d}"
            else:
                export_period = f"{loaded_period[0]}-{loaded_period[1]}"

            source_export_slug = "_".join(source.lower() for source in usable_sources)
            export_name = (
                f"ons_{source_export_slug}_{subsystem_slug(subsystem_key)}_"
                f"{GRANULARITY_SLUGS[granularity]}_{export_period}.csv"
            )
            st.download_button(
                ui_text("download_csv"),
                data=csv_bytes(summary) if not summary.empty else b"",
                file_name=export_name,
                mime="text/csv",
                type="primary",
                width="stretch",
                disabled=summary.empty,
            )
            st.caption(ui_text("csv_note"))

        if not summary.empty:
            if status_columns:
                complete_mask = summary[status_columns].fillna("").eq("Completo").all(axis=1)
                complete_periods = int(complete_mask.sum())
            else:
                complete_periods = 0
            coverage = (
                float(summary[coverage_columns].stack().mean())
                if coverage_columns
                else 0.0
            )
            with st.container(border=True, key="output_kpis"):
                st.markdown(
                    f'<div class="panel-kicker">{ui_text("summary_kicker")}</div>',
                    unsafe_allow_html=True,
                )
                first_metric_row = st.columns(2, gap="small")
                first_metric_row[0].metric(ui_text("discretization"), granularity_label)
                first_metric_row[1].metric(ui_text("result_rows"), len(summary))
                second_metric_row = st.columns(2, gap="small")
                second_metric_row[0].metric(ui_text("complete_periods"), complete_periods)
                second_metric_row[1].metric(ui_text("average_coverage"), f"{coverage:.1f}%")

    with table_column:
        st.subheader(
            GRANULARITY_TITLES[language][granularity].format(
                subsystem=selected_subsystem_label
            )
        )
        if granularity == "daily" and analysis_start and analysis_end:
            table_note = ui_text("period_shown").format(
                start=f"{analysis_start:%d/%m/%Y}",
                end=f"{analysis_end:%d/%m/%Y}",
            )
        else:
            table_note = ui_text("period_shown").format(
                start=loaded_period[0], end=loaded_period[1]
            )
        st.markdown(
            f'<p class="small-note">{table_note} {ui_text("values_note")}</p>',
            unsafe_allow_html=True,
        )
        if summary.empty:
            st.info(ui_text("adjust_config"))
        else:
            display_table(summary, visible_metric_columns)

chart_column, report_column = st.columns([1.55, 1], gap="large")
with chart_column:
    st.subheader(CHART_TITLES[language][granularity])
    if summary.empty or not visible_metric_columns:
        st.info(ui_text("chart_empty"))
    else:
        current_chart_metric = st.session_state.get("chart_metric")
        if current_chart_metric not in visible_metric_columns:
            st.session_state.pop("chart_metric", None)
        chart_metric = st.selectbox(
            ui_text("metric_selector"),
            options=visible_metric_columns,
            index=0,
            key="chart_metric",
        )
        if granularity == "monthly":
            chart = summary.sort_values("__period_start", kind="stable").set_index("__period_start")[[chart_metric]]
            x_label = ui_text("x_month_year")
        elif granularity == "daily":
            chart = summary.set_index("Data")[[chart_metric]]
            x_label = ui_text("x_date")
        else:
            chart = summary.set_index("Ano")[[chart_metric]]
            x_label = ui_text("x_year")
        st.line_chart(chart, x_label=x_label, y_label=chart_metric)

with report_column:
    st.subheader(ui_text("processed_files"))
    report_frames: list[pd.DataFrame] = []
    for source in usable_sources:
        report = results[source].file_report.copy()
        report.insert(0, ui_text("base_column"), SOURCE_LABELS[language][source])
        report_frames.append(report)
    unified_report = pd.concat(report_frames, ignore_index=True, sort=False) if report_frames else pd.DataFrame()
    st.dataframe(
        unified_report,
        width="stretch",
        hide_index=True,
        height=min(445, 96 + 35 * len(unified_report)),
        column_config={
            "Ano": st.column_config.NumberColumn(format="%d"),
            "Linhas horárias do SIN": st.column_config.NumberColumn(format="%d"),
            "Linhas diárias": st.column_config.NumberColumn(format="%d"),
            "Meses": st.column_config.NumberColumn(format="%d"),
            "Subsistemas": st.column_config.NumberColumn(format="%d"),
            "Duplicatas removidas": st.column_config.NumberColumn(format="%d"),
        },
    )
