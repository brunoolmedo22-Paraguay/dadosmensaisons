from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

import pandas as pd
import streamlit as st

from balanco_ons import ProcessingResult, build_csv_export, process_parquet_files
from ons_download import ONSDownloadError, download_parquet_years


FIRST_AVAILABLE_YEAR = 2000
CURRENT_YEAR = date.today().year


st.set_page_config(
    page_title="Balanço Mensal do SIN",
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


def csv_bytes(data: pd.DataFrame) -> bytes:
    return build_csv_export(data).to_csv(
        index=False,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
    ).encode("utf-8-sig")


def display_table(data: pd.DataFrame, metrics: Sequence[str]) -> None:
    visible = data.drop(columns=["Mês nº"])
    config: dict[str, object] = {
        "Ano": st.column_config.NumberColumn(format="%d"),
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
        <h1 class="hero-title">Balanço Mensal do SIN</h1>
        <p class="hero-copy">
            Escolha o período e transforme automaticamente os dados horários
            publicados pelo ONS em uma série de médias mensais do SIN.
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
                    <strong>Consolidar o SIN</strong>
                    <p>Calcula as médias mensais e libera indicadores, gráficos e CSV.</p>
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
    st.session_state.pop("display_years", None)
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

if result.monthly.empty:
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

available_years = sorted(result.monthly["Ano"].unique().tolist())
filter_column, _ = st.columns(2, gap="large")
with filter_column:
    selected_years = st.multiselect(
        "Anos exibidos",
        options=available_years,
        default=available_years,
        key="display_years",
    )

if not selected_years:
    st.info("Selecione ao menos um ano na barra lateral.")
    st.stop()

filtered = result.monthly.loc[
    result.monthly["Ano"].isin(selected_years)
].reset_index(drop=True)

metric_columns = result.metric_columns
complete_months = int(filtered["Status do mês"].eq("Completo").sum())
coverage = float(filtered["Cobertura (%)"].mean())

metric_cards = st.columns(4)
metric_cards[0].metric("Anos consolidados", filtered["Ano"].nunique())
metric_cards[1].metric("Meses disponíveis", len(filtered))
metric_cards[2].metric("Meses completos", complete_months)
metric_cards[3].metric("Cobertura média", f"{coverage:.1f}%")

st.subheader("Médias mensais do SIN")
st.markdown(
    '<p class="small-note">Valores energéticos expressos como potência média '
    "no mês (MWmed). A cobertura permite identificar meses ainda parciais.</p>",
    unsafe_allow_html=True,
)
display_table(filtered, metric_columns)

export_years = "-".join(map(str, selected_years))
st.download_button(
    "Baixar tabela consolidada em CSV",
    data=csv_bytes(filtered),
    file_name=f"balanco_mensal_sin_{export_years}.csv",
    mime="text/csv",
    width="stretch",
)
st.caption(
    "O CSV contém somente ano, mês, gerações, carga e intercâmbio. "
    "Formato UTF-8, com ponto e vírgula e vírgula decimal."
)

left, right = st.columns([1.55, 1])
with left:
    st.subheader("Comparação entre anos")
    chart_metric = st.selectbox(
        "Grandeza",
        options=metric_columns,
        index=0,
    )
    chart = filtered.pivot(
        index="Mês nº",
        columns="Ano",
        values=chart_metric,
    ).reindex(range(1, 13))
    chart.index = [MONTH for MONTH in (
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez"
    )]
    chart.columns = chart.columns.astype(str)
    st.line_chart(chart, x_label="Mês", y_label=chart_metric)

with right:
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
