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
    initial_sidebar_state="expanded",
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
    st.subheader("Como funciona")
    columns = st.columns(3)
    cards = [
        (
            "1",
            "Selecione o período",
            "Escolha o primeiro e o último ano que deseja analisar.",
        ),
        (
            "2",
            "Baixe os dados",
            "A aplicação localiza e baixa os arquivos Parquet diretamente do ONS.",
        ),
        (
            "3",
            "Analise e exporte",
            "As médias mensais ficam prontas para comparar e baixar em CSV.",
        ),
    ]
    for column, (number, title, body) in zip(columns, cards):
        with column:
            st.markdown(
                f"""
                <div class="empty-card">
                    <div class="step-number">{number}</div>
                    <h3>{title}</h3>
                    <p>{body}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.info(
        "Os arquivos são obtidos do Portal de Dados Abertos do ONS somente "
        "quando você clicar em **Baixar dados do ONS**."
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

with st.sidebar:
    st.header("Período de análise")
    default_start = max(FIRST_AVAILABLE_YEAR, CURRENT_YEAR - 4)
    selected_period = st.select_slider(
        "Selecione o intervalo de anos",
        options=list(range(FIRST_AVAILABLE_YEAR, CURRENT_YEAR + 1)),
        value=(default_start, CURRENT_YEAR),
        help="Os dois extremos do intervalo serão incluídos no processamento.",
    )
    download_clicked = st.button(
        "Baixar dados do ONS",
        type="primary",
        width="stretch",
    )
    st.caption(
        "A página oficial é consultada no momento do clique. Os arquivos "
        "Parquet são mantidos apenas durante o processamento."
    )
    st.divider()
    st.markdown("**Regra de cálculo**")
    st.caption(
        "Filtro: `id_subsistema = SIN`  \n"
        "Agregação: média aritmética das observações de cada mês."
    )

start_year, end_year = (int(value) for value in selected_period)
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
with st.sidebar:
    st.divider()
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
