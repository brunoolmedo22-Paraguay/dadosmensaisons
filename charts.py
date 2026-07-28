from __future__ import annotations

import altair as alt
import pandas as pd


MONTH_SHORT = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}


def generation_variation_chart(
    data: pd.DataFrame,
    metric: str,
    source_name: str,
) -> alt.Chart:
    """Cria um gráfico mensal, com uma linha para cada ano selecionado."""
    chart_data = data[["Ano", "Mês nº", "Mês", metric]].dropna().copy()
    chart_data["Ano"] = chart_data["Ano"].astype(str)
    chart_data["Mês curto"] = chart_data["Mês nº"].map(MONTH_SHORT)
    chart_data = chart_data.rename(columns={metric: "Geração (MWmed)"})

    return (
        alt.Chart(chart_data)
        .mark_line(
            point={"filled": True, "size": 55},
            strokeWidth=2.5,
        )
        .encode(
            x=alt.X(
                "Mês curto:N",
                title="Mês",
                sort=list(MONTH_SHORT.values()),
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(
                "Geração (MWmed):Q",
                title="MWmed",
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color(
                "Ano:N",
                title="Ano",
                scale=alt.Scale(scheme="tableau10"),
            ),
            tooltip=[
                alt.Tooltip("Ano:N", title="Ano"),
                alt.Tooltip("Mês:N", title="Mês"),
                alt.Tooltip(
                    "Geração (MWmed):Q",
                    title="Geração média",
                    format=",.2f",
                ),
            ],
        )
        .properties(
            title=f"Geração {source_name.lower()}",
            height=250,
        )
        .configure_axis(
            gridColor="#E2EBEA",
            domainColor="#A8B9B8",
            labelColor="#496264",
            titleColor="#17383B",
        )
        .configure_legend(
            orient="top",
            direction="horizontal",
            title=None,
        )
        .configure_title(
            anchor="start",
            color="#17383B",
            fontSize=16,
        )
        .configure_view(strokeWidth=0)
    )
