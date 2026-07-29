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
    "hourly": "Série horária do SIN",
    "daily": "Médias diárias do SIN",
    "monthly": "Médias mensais do SIN",
    "yearly": "Médias anuais do SIN",
}
GRANULARITY_SLUGS: dict[Granularity, str] = {
    "hourly": "horario",
    "daily": "diario",
    "monthly": "mensal",
    "yearly": "anual",
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
            box-shadow: 0 8px 24px var(--soft-shadow);
        }
        .st-key-output_kpis {
            background: var(--surface);
            border: none !important;
            border-radius: 18px;
            padding: .9rem 1rem 1rem;
            box-shadow: 0 6px 18px var(--soft-shadow);
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
            box-shadow: 0 8px 24px var(--soft-shadow);
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
            color: var(--brand-readable);
            font-size: .78rem;
            font-weight: 650;
            margin: 1rem 0 0;
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

default_start = max(FIRST_AVAILABLE_YEAR, CURRENT_YEAR - 4)
with st.container(border=True, key="download_panel"):
    st.markdown(
        '<div class="panel-kicker">Obtenção automática</div>',
        unsafe_allow_html=True,
    )
    left_column, right_column = st.columns([1.15, 1], gap="large")

    with left_column:
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

    with right_column:
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
                        <strong>Preparar a série do SIN</strong>
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
timestamps = pd.to_datetime(result.hourly["din_instante"], errors="coerce").dropna()
data_min = timestamps.min().date()
data_max = timestamps.max().date()

with st.container(border=True, key="results_panel"):
    table_column, settings_column = st.columns([1.7, 1], gap="large")

    with settings_column:
        with st.container(border=True, key="output_panel"):
            st.markdown(
                '<div class="panel-kicker">Configuração da saída</div>',
                unsafe_allow_html=True,
            )
            st.subheader("Discretização e CSV")
            granularity_label = st.selectbox(
                "Discretização dos dados",
                options=list(GRANULARITY_OPTIONS),
                index=2,
                key="granularity_label",
            )
            granularity = GRANULARITY_OPTIONS[granularity_label]

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
                    f"{loaded_period[0]}_{loaded_period[1]}_{granularity}"
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
            else:
                st.info(
                    f"Todo o intervalo baixado, de {loaded_period[0]} a "
                    f"{loaded_period[1]}, será incluído."
                )

            if valid_dates:
                summary = build_period_summary(
                    result.hourly,
                    granularity=granularity,
                    start_date=analysis_start,
                    end_date=analysis_end,
                )
            else:
                summary = pd.DataFrame()

            st.divider()
            if summary.empty:
                st.warning("Não há dados para a configuração selecionada.")

            if analysis_start is not None and analysis_end is not None:
                export_period = (
                    f"{analysis_start:%Y%m%d}-{analysis_end:%Y%m%d}"
                )
            else:
                export_period = f"{loaded_period[0]}-{loaded_period[1]}"

            export_name = (
                f"balanco_sin_{GRANULARITY_SLUGS[granularity]}_"
                f"{export_period}.csv"
            )
            st.download_button(
                "Baixar dados consolidados em CSV",
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
                "O CSV corresponde exatamente à discretização e ao período "
                "mostrados na tabela."
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
        st.subheader(GRANULARITY_TITLES[granularity])
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
            display_table(summary, metric_columns)

chart_column, report_column = st.columns([1.55, 1], gap="large")
with chart_column:
    chart_titles: dict[Granularity, str] = {
        "hourly": "Evolução horária",
        "daily": "Evolução diária",
        "monthly": "Comparação mensal entre anos",
        "yearly": "Evolução anual",
    }
    st.subheader(chart_titles[granularity])
    if summary.empty:
        st.info("O gráfico será exibido quando houver dados na tabela.")
    else:
        chart_metric = st.selectbox(
            "Grandeza",
            options=metric_columns,
            index=0,
            key="chart_metric",
        )
        if granularity == "monthly":
            chart = summary.pivot(
                index="Mês nº",
                columns="Ano",
                values=chart_metric,
            ).reindex(range(1, 13))
            chart.index = [
                "Jan",
                "Fev",
                "Mar",
                "Abr",
                "Mai",
                "Jun",
                "Jul",
                "Ago",
                "Set",
                "Out",
                "Nov",
                "Dez",
            ]
            chart.columns = chart.columns.astype(str)
            x_label = "Mês"
        elif granularity == "hourly":
            chart = summary.set_index("Data e hora")[[chart_metric]]
            x_label = "Data e hora"
        elif granularity == "daily":
            chart = summary.set_index("Data")[[chart_metric]]
            x_label = "Data"
        else:
            chart = summary.set_index("Ano")[[chart_metric]]
            x_label = "Ano"
        st.line_chart(chart, x_label=x_label, y_label=chart_metric)

with report_column:
    st.subheader("Arquivos processados")
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
