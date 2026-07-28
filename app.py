from __future__ import annotations

from typing import Sequence

import pandas as pd
import streamlit as st

from balanco_ons import (
    GENERATION_SOURCES,
    ProcessingResult,
    build_csv_export,
    build_excel_export,
    build_generation_chart_export,
    process_uploads,
)
from charts import generation_variation_chart


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


@st.cache_data(show_spinner=False)
def process_cached(
    payload: tuple[tuple[str, bytes], ...],
) -> ProcessingResult:
    return process_uploads(payload)


def csv_bytes(data: pd.DataFrame) -> bytes:
    return build_csv_export(data).to_csv(
        index=False,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
    ).encode("utf-8-sig")


def chart_csv_bytes(data: pd.DataFrame) -> bytes:
    return build_generation_chart_export(data).to_csv(
        index=False,
        sep=";",
        decimal=",",
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
        use_container_width=True,
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
            "Carregue os arquivos",
            "Envie um ou vários Excel do ONS. Cada nome deve conter o ano dos dados.",
        ),
        (
            "2",
            "Consolidação automática",
            "A aplicação seleciona somente o SIN e calcula as médias de cada mês.",
        ),
        (
            "3",
            "Baixe o resultado",
            "A tabela consolidada fica pronta para baixar em CSV ou Excel.",
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
        "Exemplo de nome válido: **BALANCO_ENERGIA_SUBSISTEMA_2026.xlsx**"
    )


st.markdown(
    """
    <section class="hero">
        <div class="hero-kicker">ONS · Consolidação histórica</div>
        <h1 class="hero-title">Balanço Mensal do SIN</h1>
        <p class="hero-copy">
            Transforme arquivos horários de balanço energético por subsistema
            em uma única série de médias mensais do Sistema Interligado Nacional.
        </p>
    </section>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Arquivos de entrada")
    uploads = st.file_uploader(
        "Excel do ONS",
        type=["xlsx", "xlsm", "xls"],
        accept_multiple_files=True,
        help=(
            "O ano é lido do nome de cada arquivo. Você pode selecionar "
            "vários anos de uma vez."
        ),
    )
    st.caption(
        "Os arquivos são processados em memória e não são gravados pela aplicação."
    )
    st.divider()
    st.markdown("**Regra de cálculo**")
    st.caption(
        "Filtro: `id_subsistema = SIN`  \n"
        "Agregação: média aritmética das observações de cada mês."
    )

if not uploads:
    render_empty_state()
    st.stop()

payload = tuple((uploaded.name, uploaded.getvalue()) for uploaded in uploads)
with st.spinner("Lendo e consolidando os arquivos..."):
    result = process_cached(payload)

for message in result.errors:
    st.error(message)
for message in result.warnings:
    st.warning(message)

if result.monthly.empty:
    st.error(
        "Nenhum resultado pôde ser gerado. Revise os nomes e a estrutura dos arquivos."
    )
    st.stop()

available_years = sorted(result.monthly["Ano"].unique().tolist())
with st.sidebar:
    st.divider()
    selected_years = st.multiselect(
        "Anos exibidos",
        options=available_years,
        default=available_years,
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
csv_column, excel_column = st.columns(2)
with csv_column:
    st.download_button(
        "Baixar tabela em CSV",
        data=csv_bytes(filtered),
        file_name=f"balanco_mensal_sin_{export_years}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with excel_column:
    st.download_button(
        "Baixar tabela em Excel",
        data=build_excel_export(filtered),
        file_name=f"balanco_mensal_sin_{export_years}.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        use_container_width=True,
    )
st.caption(
    "Os dois arquivos contêm somente ano, mês, gerações, carga e intercâmbio. "
    "O CSV usa UTF-8, ponto e vírgula e vírgula decimal."
)

st.subheader("Variação mensal da geração por fonte")
chart_intro, chart_download = st.columns([2.2, 1])
with chart_intro:
    st.markdown(
        '<p class="small-note">Cada gráfico mostra uma linha por ano, '
        "permitindo comparar o comportamento mensal de cada fonte.</p>",
        unsafe_allow_html=True,
    )
with chart_download:
    st.download_button(
        "Baixar dados dos gráficos em CSV",
        data=chart_csv_bytes(filtered),
        file_name=f"variacao_geracao_por_fonte_{export_years}.csv",
        mime="text/csv",
        use_container_width=True,
    )

source_items = list(GENERATION_SOURCES.items())
for start in range(0, len(source_items), 2):
    chart_columns = st.columns(2)
    for column, (metric, source_name) in zip(
        chart_columns,
        source_items[start : start + 2],
    ):
        with column:
            if metric in filtered.columns and filtered[metric].notna().any():
                st.altair_chart(
                    generation_variation_chart(
                        filtered,
                        metric,
                        source_name,
                    ),
                    use_container_width=True,
                )
            else:
                st.info(f"Sem dados de geração {source_name.lower()}.")

with st.expander("Ver arquivos processados"):
    st.dataframe(
        result.file_report,
        use_container_width=True,
        hide_index=True,
        height=min(445, 96 + 35 * len(result.file_report)),
        column_config={
            "Ano": st.column_config.NumberColumn(format="%d"),
            "Linhas horárias do SIN": st.column_config.NumberColumn(format="%d"),
            "Meses": st.column_config.NumberColumn(format="%d"),
            "Duplicatas removidas": st.column_config.NumberColumn(format="%d"),
        },
    )
