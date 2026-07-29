from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

import pandas as pd
import streamlit as st

from balanco_ons import (
    Granularity,
    ProcessingResult,
    SUBSYSTEM_LABELS,
    build_granular_csv_export,
    build_period_summary,
    process_parquet_files,
)
from ons_download import ONSDownloadError, download_parquet_years


FIRST_AVAILABLE_YEAR = 2000
CURRENT_YEAR = date.today().year
GRANULARITY_OPTIONS: dict[str, Granularity] = {
    "Horária": "hourly",
    "Diária": "daily",
    "Mensal": "monthly",
    "Anual": "yearly",
}
GRANULARITY_TITLES: dict[Granularity, str] = {
    "hourly": "Série horária",
    "daily": "Médias diárias",
    "monthly": "Médias mensais",
    "yearly": "Médias anuais",
}
GRANULARITY_SLUGS: dict[Granularity, str] = {
    "hourly": "horario",
    "daily": "diario",
    "monthly": "mensal",
    "yearly": "anual",
}
SUBSYSTEM_SLUGS = {
    SUBSYSTEM_LABELS["SIN"]: "sin",
    SUBSYSTEM_LABELS["SE"]: "seco",
    SUBSYSTEM_LABELS["S"]: "sul",
    SUBSYSTEM_LABELS["NE"]: "nordeste",
    SUBSYSTEM_LABELS["N"]: "norte",
}


st.set_page_config(
    page_title="Balanço Energético do SIN",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        :root {
            --ink: #17383b;
            --muted: #5c7072;
            --brand: #006b70;
            --brand-dark: #004e52;
            --accent: #e2ad21;
            --surface: #ffffff;
            --line: #dce7e6;
        }
        .stApp {
            background:
                radial-gradient(circle at 90% -10%, rgba(0, 107, 112, .12), transparent 31rem),
                #f6f8f8;
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
        .empty-card {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 16px;
            min-height: 9.2rem;
            padding: 1.25rem;
            box-shadow: 0 4px 16px rgba(20, 61, 64, .04);
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
            background: rgba(255, 255, 255, .88);
            border: 1px solid var(--line);
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
            color: var(--brand);
            font-size: .72rem;
            font-weight: 750;
            letter-spacing: .11em;
            text-transform: uppercase;
            margin-bottom: .2rem;
        }
        .st-key-download_panel {
            background: rgba(255, 255, 255, .92);
            border-color: var(--line) !important;
            border-radius: 18px;
            min-height: 20.25rem;
            padding: 1.15rem 1.25rem;
            box-shadow: 0 8px 24px rgba(20, 61, 64, .06);
        }
        .st-key-output_panel {
            background: rgba(255, 255, 255, .92);
            border-color: var(--line) !important;
            border-radius: 18px;
            padding: 1.05rem 1.15rem;
            box-shadow: 0 8px 24px rgba(20, 61, 64, .05);
        }
        .st-key-output_kpis {
            background: rgba(255, 255, 255, .92);
            border-color: var(--line) !important;
            border-radius: 18px;
            padding: .9rem 1rem 1rem;
            box-shadow: 0 6px 18px rgba(20, 61, 64, .04);
        }
        .st-key-output_kpis [data-testid="stMetric"] {
            min-height: 5rem;
            padding: .65rem .75rem;
            background: #f7fbfb;
            border-color: rgba(20, 61, 64, .12);
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
        .process-card {
            min-height: 20.25rem;
            padding: 1.35rem 1.45rem;
            border: 1px solid rgba(0, 107, 112, .20);
            border-radius: 18px;
            background:
                linear-gradient(145deg, rgba(226, 246, 244, .92), rgba(255, 255, 255, .96));
            box-shadow: 0 8px 24px rgba(20, 61, 64, .06);
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
        .process-foot {
            color: var(--brand-dark);
            font-size: .78rem;
            font-weight: 650;
            margin: 1rem 0 0;
        }
        .result-placeholder {
            margin-top: 1.25rem;
            padding: 1.7rem;
            color: var(--muted);
            text-align: center;
            border: 1px dashed #bfd1d0;
            border-radius: 16px;
            background: rgba(255, 255, 255, .58);
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


def csv_bytes(
    data: pd.DataFrame,
    granularity: Granularity,
    metric_columns: Sequence[str],
) -> bytes:
    return build_granular_csv_export(
        data,
        granularity,
        metric_columns=metric_columns,
    ).to_csv(
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
        """
        <section class="result-placeholder">
            <h3>Os resultados aparecerão aqui</h3>
            <p>
                Defina o período acima e clique em <strong>Baixar dados do ONS</strong>
                para iniciar a análise.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def obtain_ons_data(
    start_year: int,
    end_year: int,
) -> tuple[ProcessingResult, int]:
    years = list(range(start_year, end_year + 1))
    progress = st.progress(2, text="Consultando o catálogo do ONS...")

    def update_progress(completed: int, total: int, year: int) -> None:
        percentage = 5 + int(75 * completed / total)
        progress.progress(
            percentage,
            text=f"Arquivo de {year} concluído ({completed}/{total})...",
        )

    try:
        with TemporaryDirectory(prefix="ons_balanco_") as temporary_directory:
            batch = download_parquet_years(
                years=years,
                destination=Path(temporary_directory),
                progress_callback=update_progress,
            )
            progress.progress(88, text="Validando e consolidando os dados...")
            result = process_parquet_files(batch.files)
            result.errors = [*batch.errors, *result.errors]
            progress.progress(100, text="Processamento concluído.")
            return result, batch.total_bytes
    finally:
        progress.empty()


st.markdown(
    """
    <section class="hero">
        <div class="hero-kicker">ONS · Consolidação histórica</div>
        <h1 class="hero-title">Balanço Energético do SIN</h1>
        <p class="hero-copy">
            Escolha o período e transforme automaticamente os dados horários
            publicados pelo ONS na discretização mais adequada para sua análise.
        </p>
    </section>
    """,
    unsafe_allow_html=True,
)

controls_column, explanation_column = st.columns(2, gap="large")

with controls_column:
    default_start = max(FIRST_AVAILABLE_YEAR, CURRENT_YEAR - 4)
    with st.container(border=True, key="download_panel"):
        st.markdown(
            '<div class="panel-kicker">Obtenção automática</div>',
            unsafe_allow_html=True,
        )
        st.subheader("Selecione o período")
        st.caption(
            "Escolha o primeiro e o último ano. Os dois extremos serão incluídos."
        )
        selected_period = st.select_slider(
            "Ano inicial e ano final",
            options=list(range(FIRST_AVAILABLE_YEAR, CURRENT_YEAR + 1)),
            value=(default_start, CURRENT_YEAR),
        )
        download_clicked = st.button(
            "Baixar dados do ONS",
            type="primary",
            width="stretch",
        )
        st.caption(
            "Fonte oficial do ONS · Formato Parquet · Processamento temporário"
        )

start_year, end_year = (int(value) for value in selected_period)

with explanation_column:
    st.markdown(
        f"""
        <section class="process-card">
            <div class="panel-kicker">Fluxo da plataforma</div>
            <h2>O que será feito?</h2>
            <p class="process-lead">
                Ao clicar no botão, a plataforma executará todo o processo
                automaticamente para o período <strong>{start_year}–{end_year}</strong>.
            </p>
            <div class="process-step">
                <div class="process-number">1</div>
                <div>
                    <strong>Localizar os arquivos</strong>
                    <p>Consulta o catálogo oficial e identifica um Parquet para cada ano.</p>
                </div>
            </div>
            <div class="process-step">
                <div class="process-number">2</div>
                <div>
                    <strong>Baixar e validar</strong>
                    <p>Salva os arquivos temporariamente e verifica o conteúdo recebido.</p>
                </div>
            </div>
            <div class="process-step">
                <div class="process-number">3</div>
                <div>
                    <strong>Preparar as séries por subsistema</strong>
                    <p>Limpa os registros horários e os deixa prontos para análise e CSV.</p>
                </div>
            </div>
            <p class="process-foot">
                Nenhum upload manual · Arquivos temporários eliminados ao final
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

download_error: str | None = None

if download_clicked:
    st.session_state.pop("ons_result", None)
    st.session_state.pop("ons_period", None)
    st.session_state.pop("ons_download_bytes", None)
    st.session_state.pop("selected_subsystem", None)
    st.session_state.pop("chart_metric", None)
    for state_key in list(st.session_state):
        if str(state_key).startswith(
            ("analysis_start_", "analysis_end_", "visible_metrics_")
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
        download_error = (
            "Ocorreu um erro inesperado durante o download ou processamento: "
            f"{exc}"
        )
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
        f"Os resultados exibidos ainda correspondem a **{loaded_start}–{loaded_end}**. "
        "Clique em **Baixar dados do ONS** para processar o novo intervalo "
        "selecionado."
    )

for message in result.errors:
    st.error(message)
for message in result.warnings:
    st.warning(message)

if result.hourly.empty:
    st.error(
        "Nenhum resultado pôde ser gerado. Verifique o período selecionado "
        "e as mensagens apresentadas acima."
    )
    st.stop()

downloaded_files = len(result.file_report)
downloaded_megabytes = (
    float(st.session_state.get("ons_download_bytes", 0)) / (1024 * 1024)
)
st.success(
    f"Dados de **{loaded_period[0]}–{loaded_period[1]}** processados: "
    f"{downloaded_files} arquivo(s) Parquet, {downloaded_megabytes:.1f} MB."
)

metric_columns = result.metric_columns
subsystem_options = getattr(result, "subsystem_options", [])
if not subsystem_options and "Subsistema" in result.hourly.columns:
    subsystem_options = (
        result.hourly["Subsistema"].dropna().astype(str).drop_duplicates().tolist()
    )
if not subsystem_options:
    subsystem_options = [SUBSYSTEM_LABELS["SIN"]]

table_column, settings_column = st.columns([1.7, 1], gap="large")

with settings_column:
    with st.container(border=True, key="output_panel"):
        st.markdown(
            '<div class="panel-kicker">Configuração da saída</div>',
            unsafe_allow_html=True,
        )
        st.subheader("Tabela, gráfico e CSV")
        default_subsystem_index = (
            subsystem_options.index(SUBSYSTEM_LABELS["SIN"])
            if SUBSYSTEM_LABELS["SIN"] in subsystem_options
            else 0
        )
        selected_subsystem = st.selectbox(
            "Subsistema",
            options=subsystem_options,
            index=default_subsystem_index,
            key="selected_subsystem",
        )
        granularity_label = st.selectbox(
            "Discretização dos dados",
            options=list(GRANULARITY_OPTIONS),
            index=2,
            key="granularity_label",
        )
        granularity = GRANULARITY_OPTIONS[granularity_label]
        subsystem_slug = SUBSYSTEM_SLUGS.get(
            selected_subsystem,
            "subsistema",
        )

        selected_hourly = result.hourly
        if "Subsistema" in selected_hourly.columns:
            selected_hourly = selected_hourly.loc[
                selected_hourly["Subsistema"].eq(selected_subsystem)
            ].copy()
        timestamps = pd.to_datetime(
            selected_hourly["din_instante"],
            errors="coerce",
        ).dropna()

        analysis_start: date | None = None
        analysis_end: date | None = None
        valid_dates = not timestamps.empty
        if valid_dates:
            data_min = timestamps.min().date()
            data_max = timestamps.max().date()
        else:
            st.warning("Não há registros para o subsistema selecionado.")

        if valid_dates and granularity in {"hourly", "daily"}:
            suggested_days = 6 if granularity == "hourly" else 30
            suggested_start = max(
                data_min,
                data_max - timedelta(days=suggested_days),
            )
            date_key = (
                f"{loaded_period[0]}_{loaded_period[1]}_"
                f"{granularity}_{subsystem_slug}"
            )
            start_column, end_column = st.columns(2, gap="small")
            with start_column:
                analysis_start = st.date_input(
                    "Data inicial",
                    value=suggested_start,
                    min_value=data_min,
                    max_value=data_max,
                    key=f"analysis_start_{date_key}",
                )
            with end_column:
                analysis_end = st.date_input(
                    "Data final",
                    value=data_max,
                    min_value=data_min,
                    max_value=data_max,
                    key=f"analysis_end_{date_key}",
                )
            if analysis_start > analysis_end:
                st.error("A data inicial deve ser anterior à data final.")
                valid_dates = False
            else:
                st.caption(
                    "Use os dois calendários para limitar o volume exibido e exportado."
                )
        elif valid_dates:
            st.info(
                f"Todo o intervalo baixado, de {loaded_period[0]} a "
                f"{loaded_period[1]}, será incluído."
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

        available_metric_columns = [
            metric
            for metric in metric_columns
            if summary.empty or metric in summary.columns
        ]
        selected_metric_columns = st.multiselect(
            "Variáveis na tabela e no gráfico",
            options=available_metric_columns,
            default=available_metric_columns,
            key=(
                f"visible_metrics_{loaded_period[0]}_{loaded_period[1]}_"
                f"{subsystem_slug}"
            ),
            help=(
                "As mesmas variáveis serão usadas na tabela, no gráfico "
                "e no arquivo CSV."
            ),
        )

        summary_metric_columns = [
            metric for metric in metric_columns if metric in summary.columns
        ]
        metadata_columns = [
            column
            for column in summary.columns
            if column not in summary_metric_columns
        ]
        table_summary = summary[
            [*metadata_columns, *selected_metric_columns]
        ].copy()

        st.divider()
        if summary.empty:
            st.warning("Não há dados para a configuração selecionada.")
        elif not selected_metric_columns:
            st.warning("Selecione ao menos uma variável para gerar a saída.")

        if analysis_start is not None and analysis_end is not None:
            export_period = (
                f"{analysis_start:%Y%m%d}-{analysis_end:%Y%m%d}"
            )
        else:
            export_period = f"{loaded_period[0]}-{loaded_period[1]}"

        export_name = (
            f"balanco_{subsystem_slug}_{GRANULARITY_SLUGS[granularity]}_"
            f"{export_period}.csv"
        )
        output_ready = not summary.empty and bool(selected_metric_columns)
        st.download_button(
            "Baixar dados consolidados em CSV",
            data=(
                csv_bytes(
                    table_summary,
                    granularity,
                    selected_metric_columns,
                )
                if output_ready
                else b""
            ),
            file_name=export_name,
            mime="text/csv",
            type="primary",
            width="stretch",
            disabled=not output_ready,
        )
        st.caption(
            "O CSV respeita o subsistema, o período, a discretização e as "
            "variáveis mostradas na tabela."
        )

    if not summary.empty:
        complete_periods = int(
            summary["Status do período"].eq("Completo").sum()
        )
        coverage = float(summary["Cobertura (%)"].mean())
        with st.container(border=True, key="output_kpis"):
            st.markdown(
                '<div class="panel-kicker">Resumo da saída</div>',
                unsafe_allow_html=True,
            )
            first_metric_row = st.columns(2, gap="small")
            first_metric_row[0].metric(
                "Discretização",
                granularity_label,
            )
            first_metric_row[1].metric(
                "Linhas no resultado",
                len(summary),
            )
            second_metric_row = st.columns(2, gap="small")
            second_metric_row[0].metric(
                "Períodos completos",
                complete_periods,
            )
            second_metric_row[1].metric(
                "Cobertura média",
                f"{coverage:.1f}%",
            )

with table_column:
    st.subheader(
        f"{GRANULARITY_TITLES[granularity]} — {selected_subsystem}"
    )
    if granularity in {"hourly", "daily"} and analysis_start and analysis_end:
        table_note = (
            f"Período exibido: {analysis_start:%d/%m/%Y} a "
            f"{analysis_end:%d/%m/%Y}."
        )
    else:
        table_note = (
            f"Período exibido: {loaded_period[0]} a {loaded_period[1]}."
        )
    st.markdown(
        f'<p class="small-note">{table_note} Valores expressos como potência '
        "média em MWmed.</p>",
        unsafe_allow_html=True,
    )
    if summary.empty:
        st.info("Ajuste a configuração ao lado para visualizar os dados.")
    else:
        display_table(table_summary, selected_metric_columns)

chart_column, report_column = st.columns([1.7, 1], gap="large")
with chart_column:
    st.subheader("Representação gráfica da tabela")
    st.caption(
        f"{selected_subsystem} · {granularity_label.lower()} · "
        "mesmas linhas e variáveis selecionadas."
    )
    if summary.empty:
        st.info("O gráfico será exibido quando houver dados na tabela.")
    elif not selected_metric_columns:
        st.info("Selecione ao menos uma variável para visualizar o gráfico.")
    else:
        chart = table_summary.set_index("__period_start")[
            selected_metric_columns
        ]
        x_labels: dict[Granularity, str] = {
            "hourly": "Data e hora",
            "daily": "Data",
            "monthly": "Mês",
            "yearly": "Ano",
        }
        st.line_chart(
            chart,
            x_label=x_labels[granularity],
            y_label="Potência média (MWmed)",
        )

with report_column:
    st.subheader("Arquivos processados")
    st.dataframe(
        result.file_report,
        width="stretch",
        hide_index=True,
        height=min(445, 96 + 35 * len(result.file_report)),
        column_config={
            "Ano": st.column_config.NumberColumn(format="%d"),
            "Registros horários": st.column_config.NumberColumn(format="%d"),
            "Meses": st.column_config.NumberColumn(format="%d"),
            "Duplicatas removidas": st.column_config.NumberColumn(format="%d"),
        },
    )
