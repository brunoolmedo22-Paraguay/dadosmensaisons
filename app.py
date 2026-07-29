from __future__ import annotations

import base64
import re
import unicodedata

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

import pandas as pd
import streamlit as st

from balanco_ons import (
    Granularity,
    ProcessingResult,
    available_subsystems,
    build_granular_csv_export,
    build_period_summary,
    filter_hourly_by_subsystem,
    process_parquet_files,
)
from ons_download import ONSDownloadError, download_parquet_years


FIRST_AVAILABLE_YEAR = 2000
CURRENT_YEAR = date.today().year
HERO_LOGO_PATH = Path(__file__).parent / "assets" / "logo_contorno_transparente.svg"
HERO_LOGO_DATA_URI = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(HERO_LOGO_PATH.read_bytes()).decode("ascii")
    if HERO_LOGO_PATH.exists()
    else ""
)
GRANULARITIES: tuple[Granularity, ...] = (
    "hourly",
    "daily",
    "monthly",
    "yearly",
)
GRANULARITY_LABELS: dict[str, dict[Granularity, str]] = {
    "PT": {
        "hourly": "Horária",
        "daily": "Diária",
        "monthly": "Mensal",
        "yearly": "Anual",
    },
    "ES": {
        "hourly": "Horaria",
        "daily": "Diaria",
        "monthly": "Mensual",
        "yearly": "Anual",
    },
}
GRANULARITY_TITLES: dict[str, dict[Granularity, str]] = {
    "PT": {
        "hourly": "Série horária — {subsystem}",
        "daily": "Médias diárias — {subsystem}",
        "monthly": "Médias mensais — {subsystem}",
        "yearly": "Médias anuais — {subsystem}",
    },
    "ES": {
        "hourly": "Serie horaria — {subsystem}",
        "daily": "Promedios diarios — {subsystem}",
        "monthly": "Promedios mensuales — {subsystem}",
        "yearly": "Promedios anuales — {subsystem}",
    },
}
CHART_TITLES: dict[str, dict[Granularity, str]] = {
    "PT": {
        "hourly": "Evolução horária",
        "daily": "Evolução diária",
        "monthly": "Evolução mensal",
        "yearly": "Evolução anual",
    },
    "ES": {
        "hourly": "Evolución horaria",
        "daily": "Evolución diaria",
        "monthly": "Evolución mensual",
        "yearly": "Evolución anual",
    },
}
MONTH_LABELS: dict[str, list[str]] = {
    "PT": [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez",
    ],
    "ES": [
        "Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
    ],
}
GRANULARITY_SLUGS: dict[Granularity, str] = {
    "hourly": "horario",
    "daily": "diario",
    "monthly": "mensal",
    "yearly": "anual",
}
UI_TEXT: dict[str, dict[str, str]] = {
    "PT": {
        "hero_kicker": "ONS · Consolidação histórica",
        "hero_title": "Balanço Energético do SIN",
        "hero_copy": (
            "Escolha o período e transforme automaticamente os dados horários "
            "publicados pelo ONS na discretização mais adequada para sua análise."
        ),
        "empty_title": "Os resultados aparecerão aqui",
        "empty_copy": (
            "Defina o período acima e clique em <strong>Baixar dados do ONS</strong> "
            "para iniciar a análise."
        ),
        "progress_catalog": "Consultando o catálogo do ONS...",
        "progress_file": "Arquivo de {year} concluído ({completed}/{total})...",
        "progress_validate": "Validando e consolidando os dados...",
        "progress_done": "Processamento concluído.",
        "auto_kicker": "Obtenção automática",
        "select_period": "Selecione o período",
        "select_period_copy": (
            "Escolha o primeiro e o último ano. Os dois extremos serão incluídos."
        ),
        "year_range": "Ano inicial e ano final",
        "download_ons": "Baixar dados do ONS",
        "source_note": (
            "Fonte oficial do ONS · Formato Parquet · Processamento temporário"
        ),
        "flow_kicker": "Fluxo da plataforma",
        "flow_title": "O que será feito?",
        "flow_lead": (
            "Ao clicar no botão, a plataforma executará todo o processo "
            "automaticamente para o período <strong>{start_year}–{end_year}</strong>."
        ),
        "step_1_title": "Localizar os arquivos",
        "step_1_copy": (
            "Consulta o catálogo oficial e identifica um Parquet para cada ano."
        ),
        "step_2_title": "Baixar e validar",
        "step_2_copy": (
            "Salva os arquivos temporariamente e verifica o conteúdo recebido."
        ),
        "step_3_title": "Preparar a série do SIN",
        "step_3_copy": (
            "Limpa os registros horários e os deixa prontos para análise e CSV."
        ),
        "unexpected_error": (
            "Ocorreu um erro inesperado durante o download ou processamento: {error}"
        ),
        "stale_results": (
            "Os resultados exibidos ainda correspondem a **{start}–{end}**. "
            "Clique em **{button}** para processar o novo intervalo selecionado."
        ),
        "no_result": (
            "Nenhum resultado pôde ser gerado. Verifique o período selecionado "
            "e as mensagens apresentadas acima."
        ),
        "processed_success": (
            "Dados de **{start}–{end}** processados: {files} arquivo(s) Parquet, "
            "{megabytes:.1f} MB."
        ),
        "output_kicker": "Configuração da saída",
        "output_title": "Subsistema, discretização e CSV",
        "subsystem_selector": "Subsistema",
        "granularity_selector": "Discretização dos dados",
        "no_subsystems": "Nenhum subsistema foi encontrado nos arquivos processados.",
        "start_date": "Data inicial",
        "end_date": "Data final",
        "invalid_dates": "A data inicial deve ser anterior à data final.",
        "calendar_note": (
            "Use os dois calendários para limitar o volume exibido e exportado."
        ),
        "full_interval": (
            "Todo o intervalo baixado, de {start} a {end}, será incluído."
        ),
        "no_data_config": "Não há dados para a configuração selecionada.",
        "download_csv": "Baixar dados consolidados em CSV",
        "csv_note": (
            "O CSV corresponde exatamente à discretização e ao período mostrados "
            "na tabela."
        ),
        "summary_kicker": "Resumo da saída",
        "discretization": "Discretização",
        "result_rows": "Linhas no resultado",
        "complete_periods": "Períodos completos",
        "average_coverage": "Cobertura média",
        "period_shown": "Período exibido: {start} a {end}.",
        "values_note": "Valores expressos como potência média em MWmed.",
        "adjust_config": (
            "Ajuste a configuração ao lado para visualizar os dados."
        ),
        "chart_empty": "O gráfico será exibido quando houver dados na tabela.",
        "metric_selector": "Grandeza",
        "x_month": "Mês",
        "x_month_year": "Mês e ano",
        "x_datetime": "Data e hora",
        "x_date": "Data",
        "x_year": "Ano",
        "processed_files": "Arquivos processados",
    },
    "ES": {
        "hero_kicker": "ONS · Consolidación histórica",
        "hero_title": "Balance Energético del SIN",
        "hero_copy": (
            "Seleccione el período y transforme automáticamente los datos horarios "
            "publicados por el ONS en la discretización más adecuada para su análisis."
        ),
        "empty_title": "Los resultados aparecerán aquí",
        "empty_copy": (
            "Defina el período anterior y pulse <strong>Descargar datos del ONS</strong> "
            "para iniciar el análisis."
        ),
        "progress_catalog": "Consultando el catálogo del ONS...",
        "progress_file": "Archivo de {year} completado ({completed}/{total})...",
        "progress_validate": "Validando y consolidando los datos...",
        "progress_done": "Procesamiento finalizado.",
        "auto_kicker": "Obtención automática",
        "select_period": "Seleccione el período",
        "select_period_copy": (
            "Seleccione el primer y el último año. Ambos extremos serán incluidos."
        ),
        "year_range": "Año inicial y año final",
        "download_ons": "Descargar datos del ONS",
        "source_note": (
            "Fuente oficial del ONS · Formato Parquet · Procesamiento temporal"
        ),
        "flow_kicker": "Flujo de la plataforma",
        "flow_title": "¿Qué se hará?",
        "flow_lead": (
            "Al pulsar el botón, la plataforma ejecutará automáticamente todo el "
            "proceso para el período <strong>{start_year}–{end_year}</strong>."
        ),
        "step_1_title": "Localizar los archivos",
        "step_1_copy": (
            "Consulta el catálogo oficial e identifica un Parquet para cada año."
        ),
        "step_2_title": "Descargar y validar",
        "step_2_copy": (
            "Guarda temporalmente los archivos y verifica el contenido recibido."
        ),
        "step_3_title": "Preparar la serie del SIN",
        "step_3_copy": (
            "Limpia los registros horarios y los deja listos para el análisis y el CSV."
        ),
        "unexpected_error": (
            "Se produjo un error inesperado durante la descarga o el procesamiento: "
            "{error}"
        ),
        "stale_results": (
            "Los resultados mostrados todavía corresponden a **{start}–{end}**. "
            "Pulse **{button}** para procesar el nuevo intervalo seleccionado."
        ),
        "no_result": (
            "No fue posible generar resultados. Verifique el período seleccionado "
            "y los mensajes mostrados anteriormente."
        ),
        "processed_success": (
            "Datos de **{start}–{end}** procesados: {files} archivo(s) Parquet, "
            "{megabytes:.1f} MB."
        ),
        "output_kicker": "Configuración de salida",
        "output_title": "Subsistema, discretización y CSV",
        "subsystem_selector": "Subsistema",
        "granularity_selector": "Discretización de los datos",
        "no_subsystems": "No se encontraron subsistemas en los archivos procesados.",
        "start_date": "Fecha inicial",
        "end_date": "Fecha final",
        "invalid_dates": "La fecha inicial debe ser anterior a la fecha final.",
        "calendar_note": (
            "Use los dos calendarios para limitar el volumen mostrado y exportado."
        ),
        "full_interval": (
            "Se incluirá todo el intervalo descargado, de {start} a {end}."
        ),
        "no_data_config": "No hay datos para la configuración seleccionada.",
        "download_csv": "Descargar datos consolidados en CSV",
        "csv_note": (
            "El CSV corresponde exactamente a la discretización y al período "
            "mostrados en la tabla."
        ),
        "summary_kicker": "Resumen de salida",
        "discretization": "Discretización",
        "result_rows": "Filas en el resultado",
        "complete_periods": "Períodos completos",
        "average_coverage": "Cobertura promedio",
        "period_shown": "Período mostrado: {start} a {end}.",
        "values_note": "Valores expresados como potencia promedio en MWmed.",
        "adjust_config": (
            "Ajuste la configuración de la derecha para visualizar los datos."
        ),
        "chart_empty": "El gráfico se mostrará cuando haya datos en la tabla.",
        "metric_selector": "Magnitud",
        "x_month": "Mes",
        "x_month_year": "Mes y año",
        "x_datetime": "Fecha y hora",
        "x_date": "Fecha",
        "x_year": "Año",
        "processed_files": "Archivos procesados",
    },
}


def ui_text(key: str) -> str:
    language = st.session_state.get("ui_language", "PT")
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

if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = "PT"

language_spacer, language_column = st.columns([8, 1], gap="small")
with language_column:
    st.segmented_control(
        "Idioma",
        options=("PT", "ES"),
        key="ui_language",
        label_visibility="collapsed",
        width="stretch",
    )

language = st.session_state["ui_language"]


def subsystem_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")
    return slug or "subsistema"


def csv_bytes(data: pd.DataFrame, granularity: Granularity) -> bytes:
    return build_granular_csv_export(data, granularity).to_csv(
        index=False,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
    ).encode("utf-8-sig")


def display_table(data: pd.DataFrame, metrics: Sequence[str]) -> None:
    visible = data.drop(
        columns=["Mês nº", "__period_start"],
        errors="ignore",
    )
    config: dict[str, object] = {
        "Ano": st.column_config.NumberColumn(format="%d"),
        "Data e hora": st.column_config.DatetimeColumn(
            format="DD/MM/YYYY HH:mm",
        ),
        "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Cobertura (%)": st.column_config.NumberColumn(format="%.1f%%"),
        "Horas com dados": st.column_config.NumberColumn(format="%d"),
        "Horas esperadas": st.column_config.NumberColumn(format="%d"),
    }
    config.update(
        {
            metric: st.column_config.NumberColumn(format="%.2f")
            for metric in metrics
        }
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
) -> tuple[ProcessingResult, int]:
    years = list(range(start_year, end_year + 1))
    progress = st.progress(2, text=ui_text("progress_catalog"))

    def update_progress(completed: int, total: int, year: int) -> None:
        percentage = 5 + int(75 * completed / total)
        progress.progress(
            percentage,
            text=ui_text("progress_file").format(
                year=year, completed=completed, total=total
            ),
        )

    try:
        with TemporaryDirectory(prefix="ons_balanco_") as temporary_directory:
            batch = download_parquet_years(
                years=years,
                destination=Path(temporary_directory),
                progress_callback=update_progress,
            )
            progress.progress(88, text=ui_text("progress_validate"))
            result = process_parquet_files(batch.files)
            result.errors = [*batch.errors, *result.errors]
            progress.progress(100, text=ui_text("progress_done"))
            return result, batch.total_bytes
    finally:
        progress.empty()


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
                    <div>
                        <strong>{ui_text("step_1_title")}</strong>
                        <p>{ui_text("step_1_copy")}</p>
                    </div>
                </div>
                <div class="process-step">
                    <div class="process-number">2</div>
                    <div>
                        <strong>{ui_text("step_2_title")}</strong>
                        <p>{ui_text("step_2_copy")}</p>
                    </div>
                </div>
                <div class="process-step">
                    <div class="process-number">3</div>
                    <div>
                        <strong>{ui_text("step_3_title")}</strong>
                        <p>{ui_text("step_3_copy")}</p>
                    </div>
                </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

download_error: str | None = None

if download_clicked:
    st.session_state.pop("ons_result", None)
    st.session_state.pop("ons_period", None)
    st.session_state.pop("ons_download_bytes", None)
    st.session_state.pop("subsystem_value", None)
    for state_key in list(st.session_state):
        if str(state_key).startswith(
            ("analysis_start_", "analysis_end_")
        ):
            st.session_state.pop(state_key, None)
    try:
        downloaded_result, downloaded_bytes = obtain_ons_data(
            start_year=start_year,
            end_year=end_year,
        )
    except ONSDownloadError as exc:
        download_error = str(exc)
    except Exception as exc:
        download_error = ui_text("unexpected_error").format(error=exc)
    else:
        st.session_state["ons_result"] = downloaded_result
        st.session_state["ons_period"] = (start_year, end_year)
        st.session_state["ons_download_bytes"] = downloaded_bytes

if download_error:
    st.error(download_error)

result = st.session_state.get("ons_result")
loaded_period = st.session_state.get("ons_period")

if result is None:
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

for message in result.errors:
    st.error(message)
for message in result.warnings:
    st.warning(message)

if result.hourly.empty:
    st.error(ui_text("no_result"))
    st.stop()

downloaded_files = len(result.file_report)
downloaded_megabytes = (
    float(st.session_state.get("ons_download_bytes", 0)) / (1024 * 1024)
)
st.success(
    ui_text("processed_success").format(
        start=loaded_period[0],
        end=loaded_period[1],
        files=downloaded_files,
        megabytes=downloaded_megabytes,
    )
)

metric_columns = result.metric_columns
subsystem_items = available_subsystems(result.hourly)
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
            selected_hourly = filter_hourly_by_subsystem(
                result.hourly, subsystem_key
            )
            timestamps = pd.to_datetime(
                selected_hourly["din_instante"], errors="coerce"
            ).dropna()
            if timestamps.empty:
                st.warning(ui_text("no_data_config"))
                st.stop()
            data_min = timestamps.min().date()
            data_max = timestamps.max().date()

            granularity = st.selectbox(
                ui_text("granularity_selector"),
                options=GRANULARITIES,
                index=2,
                key="granularity_value",
                format_func=lambda value: GRANULARITY_LABELS[language][value],
            )
            granularity_label = GRANULARITY_LABELS[language][granularity]

            analysis_start: date | None = None
            analysis_end: date | None = None
            valid_dates = True

            if granularity in {"hourly", "daily"}:
                suggested_days = 6 if granularity == "hourly" else 30
                suggested_start = max(
                    data_min,
                    data_max - timedelta(days=suggested_days),
                )
                date_key = (
                    f"{loaded_period[0]}_{loaded_period[1]}_"
                    f"{subsystem_slug(subsystem_key)}_{granularity}"
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
                summary = build_period_summary(
                    selected_hourly,
                    granularity=granularity,
                    start_date=analysis_start,
                    end_date=analysis_end,
                )
            else:
                summary = pd.DataFrame()

            st.divider()
            if summary.empty:
                st.warning(ui_text("no_data_config"))

            if analysis_start is not None and analysis_end is not None:
                export_period = (
                    f"{analysis_start:%Y%m%d}-{analysis_end:%Y%m%d}"
                )
            else:
                export_period = f"{loaded_period[0]}-{loaded_period[1]}"

            export_name = (
                f"balanco_{subsystem_slug(subsystem_key)}_"
                f"{GRANULARITY_SLUGS[granularity]}_"
                f"{export_period}.csv"
            )
            st.download_button(
                ui_text("download_csv"),
                data=(
                    csv_bytes(summary, granularity)
                    if not summary.empty
                    else b""
                ),
                file_name=export_name,
                mime="text/csv",
                type="primary",
                width="stretch",
                disabled=summary.empty,
            )
            st.caption(
                ui_text("csv_note")
            )

        if not summary.empty:
            complete_periods = int(
                summary["Status do período"].eq("Completo").sum()
            )
            coverage = float(summary["Cobertura (%)"].mean())
            with st.container(border=True, key="output_kpis"):
                st.markdown(
                    f'<div class="panel-kicker">{ui_text("summary_kicker")}</div>',
                    unsafe_allow_html=True,
                )
                first_metric_row = st.columns(2, gap="small")
                first_metric_row[0].metric(
                    ui_text("discretization"),
                    granularity_label,
                )
                first_metric_row[1].metric(
                    ui_text("result_rows"),
                    len(summary),
                )
                second_metric_row = st.columns(2, gap="small")
                second_metric_row[0].metric(
                    ui_text("complete_periods"),
                    complete_periods,
                )
                second_metric_row[1].metric(
                    ui_text("average_coverage"),
                    f"{coverage:.1f}%",
                )

    with table_column:
        st.subheader(
            GRANULARITY_TITLES[language][granularity].format(
                subsystem=selected_subsystem_label
            )
        )
        if granularity in {"hourly", "daily"} and analysis_start and analysis_end:
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
            visible_metric_columns = [
                column for column in metric_columns if column in summary.columns
            ]
            display_table(summary, visible_metric_columns)

chart_column, report_column = st.columns([1.55, 1], gap="large")
with chart_column:
    st.subheader(CHART_TITLES[language][granularity])
    if summary.empty:
        st.info(ui_text("chart_empty"))
    else:
        chart_metric = st.selectbox(
            ui_text("metric_selector"),
            options=visible_metric_columns,
            index=0,
            key="chart_metric",
        )
        if granularity == "monthly":
            chart = (
                summary.sort_values("__period_start", kind="stable")
                .set_index("__period_start")[[chart_metric]]
            )
            x_label = ui_text("x_month_year")
        elif granularity == "hourly":
            chart = summary.set_index("Data e hora")[[chart_metric]]
            x_label = ui_text("x_datetime")
        elif granularity == "daily":
            chart = summary.set_index("Data")[[chart_metric]]
            x_label = ui_text("x_date")
        else:
            chart = summary.set_index("Ano")[[chart_metric]]
            x_label = ui_text("x_year")
        st.line_chart(chart, x_label=x_label, y_label=chart_metric)

with report_column:
    st.subheader(ui_text("processed_files"))
    st.dataframe(
        result.file_report,
        width="stretch",
        hide_index=True,
        height=min(445, 96 + 35 * len(result.file_report)),
        column_config={
            "Ano": st.column_config.NumberColumn(format="%d"),
            "Linhas horárias do SIN": st.column_config.NumberColumn(format="%d"),
            "Meses": st.column_config.NumberColumn(format="%d"),
            "Duplicatas removidas": st.column_config.NumberColumn(format="%d"),
        },
    )
