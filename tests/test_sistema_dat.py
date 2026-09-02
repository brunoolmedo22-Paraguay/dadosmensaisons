from __future__ import annotations

from pathlib import Path

import pytest

from sistema_dat import SistemaDatError, parse_sistema_dat


FIXTURE_PATH = Path(__file__).parents[3] / "upload" / "sistema(1).dat"


@pytest.fixture(scope="module")
def parsed():
    if not FIXTURE_PATH.exists():
        pytest.skip("Amostra real disponível apenas no ambiente de desenvolvimento.")
    return parse_sistema_dat(FIXTURE_PATH.read_bytes())


def _month_line(year: int, values: dict[int, float]) -> str:
    fields = [" " * 8 for _ in range(12)]
    for month, value in values.items():
        fields[month - 1] = f"{value:8.2f}"
    return f"{year:<6}" + "".join(fields)


def _minimal_sistema(year: int, months: tuple[int, ...]) -> str:
    market_blocks: list[str] = []
    for subsystem in range(1, 5):
        market_blocks.extend(
            [f"   {subsystem}", _month_line(year, {month: 1000.0 for month in months})]
        )
    generation_blocks: list[str] = []
    source_labels = ("PCH", "PCT", "EOL", "UFV", "PCH MMGD", "PCT MMGD", "EOL MMGD", "UFV MMGD")
    for block_code, source in enumerate(source_labels, start=1):
        generation_blocks.extend(
            [f"   1    {block_code}  {source}", _month_line(year, {month: 10.0 for month in months})]
        )
    return "\n".join(
        [
            " PATAMAR DE DEFICIT",
            " NUMERO DE PATAMARES DE DEFICIT",
            " XXX",
            "   1",
            " CUSTO DO DEFICIT",
            " 1 SUDESTE 0 1000.00 0.00 0.00 0.00 1.000 0.000 0.000 0.000",
            " 999",
            " MERCADO DE ENERGIA TOTAL",
            " XXX",
            "       XXXJAN. XXXFEV. XXXMAR. XXXABR. XXXMAI. XXXJUN. XXXJUL. XXXAGO. XXXSET. XXXOUT. XXXNOV. XXXDEZ.",
            *market_blocks,
            " 999",
            " GERACAO DE USINAS NAO SIMULADAS",
            " XXX  XBL  XXXXXXXXXXXXXXXXXXXX  XTE",
            "       XXXJAN. XXXFEV. XXXMAR. XXXABR. XXXMAI. XXXJUN. XXXJUL. XXXAGO. XXXSET. XXXOUT. XXXNOV. XXXDEZ.",
            *generation_blocks,
            " 999",
        ]
    )


@pytest.mark.parametrize(
    ("year", "months"),
    [
        (2027, (1, 2, 3)),
        (2028, (5, 6, 7, 8, 9)),
        (2031, tuple(range(1, 13))),
    ],
)
def test_detects_each_uploaded_file_horizon_from_its_occupied_month_fields(
    year: int,
    months: tuple[int, ...],
) -> None:
    parsed_file = parse_sistema_dat(_minimal_sistema(year, months))
    dates = parsed_file.monthly_summary["date"]

    assert dates.min().year == year
    assert dates.min().month == min(months)
    assert dates.max().month == max(months)
    assert len(dates) == len(months)


def test_reads_the_fixed_width_study_period_without_month_shift(parsed) -> None:
    summary = parsed.monthly_summary

    assert summary["date"].min().strftime("%Y-%m") == "2026-09"
    assert summary["date"].max().strftime("%Y-%m") == "2030-12"
    assert len(summary) == 52


def test_aggregates_market_and_global_load(parsed) -> None:
    first = parsed.monthly_summary.iloc[0]

    assert first["market_sin_mwmed"] == pytest.approx(76_391.0)
    assert first["mmgd_total_mwmed"] == pytest.approx(8_964.0)
    assert first["global_load_mwmed"] == pytest.approx(85_355.0)


def test_separates_central_and_distributed_generation(parsed) -> None:
    first = parsed.monthly_summary.iloc[0]

    assert first["wind_central_mwmed"] == pytest.approx(15_425.0)
    assert first["solar_central_mwmed"] == pytest.approx(4_755.0)
    assert first["wind_mmgd_mwmed"] == pytest.approx(10.47)
    assert first["solar_mmgd_mwmed"] == pytest.approx(8_769.4)


def test_reads_both_interchange_directions_and_unbounded_marker(parsed) -> None:
    interchanges = parsed.interchanges

    assert {1, 2, 3, 4, 11}.issubset(
        set(interchanges["origin_code"]) | set(interchanges["destination_code"])
    )
    assert interchanges["is_unbounded"].any()
    assert (
        (interchanges["origin_code"] == 1)
        & (interchanges["destination_code"] == 2)
    ).any()
    assert (
        (interchanges["origin_code"] == 2)
        & (interchanges["destination_code"] == 1)
    ).any()


def test_reads_deficit_cost(parsed) -> None:
    southeast = parsed.deficit_costs.loc[
        parsed.deficit_costs["subsystem_code"].eq(1)
    ].iloc[0]

    assert parsed.deficit_tiers == 1
    assert southeast["deficit_cost_tier_1"] == pytest.approx(8_291.25)
    assert southeast["cut_fraction_tier_1"] == pytest.approx(1.0)


def test_rejects_unrelated_text() -> None:
    with pytest.raises(SistemaDatError, match="NEWAVE"):
        parse_sistema_dat(b"not a sistema.dat")
