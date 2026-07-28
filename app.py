from __future__ import annotations

from typing import Sequence

import pandas as pd
import streamlit as st

from balanco_ons import ProcessingResult, process_uploads


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
    return data.to_csv(
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
            "A tabela consolidada fica pronta em CSV compatível com Excel em português.",
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
st.download_button(
    "Baixar tabela consolidada em CSV",
    data=csv_bytes(filtered.drop(columns=["Mês nº"])),
    file_name=f"balanco_mensal_sin_{export_years}.csv",
    mime="text/csv",
    use_container_width=True,
)
st.caption(
    "CSV em UTF-8, separado por ponto e vírgula e com vírgula decimal, "
    "pronto para abrir no Excel em português."
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
