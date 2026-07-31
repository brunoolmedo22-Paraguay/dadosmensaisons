from __future__ import annotations

import pandas as pd

from power_panel_v2 import (
    BALANCE_DIFFERENCE_COLUMN,
    DUCK_CURVE_COLUMN,
    HYDRO_COLUMN,
    LOAD_COLUMN,
    PERIOD_COLUMN,
    SOLAR_COLUMN,
    THERMAL_COLUMN,
    TOTAL_GENERATION_COLUMN,
    VARIABLE_RENEWABLE_COLUMN,
    WIND_COLUMN,
    material_balance_difference,
    prepare_power_panel_data,
)


def test_prepares_duck_curve_and_generation_stack() -> None:
    source = pd.DataFrame(
        {
            PERIOD_COLUMN: [pd.Timestamp("2026-01-01 12:00")],
            LOAD_COLUMN: [100.0],
            HYDRO_COLUMN: [50.0],
            THERMAL_COLUMN: [20.0],
            WIND_COLUMN: [15.0],
            SOLAR_COLUMN: [10.0],
        }
    )

    result = prepare_power_panel_data(source)

    assert result.loc[0, VARIABLE_RENEWABLE_COLUMN] == 25.0
    assert result.loc[0, DUCK_CURVE_COLUMN] == 75.0
    assert result.loc[0, TOTAL_GENERATION_COLUMN] == 95.0
    assert result.loc[0, BALANCE_DIFFERENCE_COLUMN] == 5.0


def test_missing_generation_source_is_treated_as_zero() -> None:
    source = pd.DataFrame(
        {
            PERIOD_COLUMN: [pd.Timestamp("2026-01-01")],
            LOAD_COLUMN: [100.0],
            HYDRO_COLUMN: [80.0],
        }
    )

    result = prepare_power_panel_data(source)

    assert result.loc[0, THERMAL_COLUMN] == 0.0
    assert result.loc[0, WIND_COLUMN] == 0.0
    assert result.loc[0, SOLAR_COLUMN] == 0.0
    assert result.loc[0, DUCK_CURVE_COLUMN] == 100.0


def test_missing_load_or_period_returns_empty() -> None:
    assert prepare_power_panel_data(pd.DataFrame({LOAD_COLUMN: [1.0]})).empty
    assert prepare_power_panel_data(pd.DataFrame({PERIOD_COLUMN: [pd.Timestamp("2026-01-01")]})).empty


def test_detects_material_difference_between_load_and_sources() -> None:
    source = pd.DataFrame(
        {
            PERIOD_COLUMN: pd.date_range("2026-01-01", periods=2),
            LOAD_COLUMN: [100.0, 100.0],
            HYDRO_COLUMN: [50.0, 50.0],
            THERMAL_COLUMN: [20.0, 20.0],
            WIND_COLUMN: [10.0, 10.0],
            SOLAR_COLUMN: [0.0, 0.0],
        }
    )
    result = prepare_power_panel_data(source)
    assert material_balance_difference(result)


def test_duck_curve_can_ignore_wind_generation() -> None:
    source = pd.DataFrame(
        {
            PERIOD_COLUMN: [pd.Timestamp("2026-01-01 12:00")],
            LOAD_COLUMN: [100.0],
            WIND_COLUMN: [15.0],
            SOLAR_COLUMN: [10.0],
        }
    )

    result = prepare_power_panel_data(
        source,
        include_wind_in_duck_curve=False,
    )

    assert result.loc[0, VARIABLE_RENEWABLE_COLUMN] == 10.0
    assert result.loc[0, DUCK_CURVE_COLUMN] == 90.0


def test_normalizes_source_order_without_duplicates() -> None:
    from power_panel_v2 import normalize_source_order

    assert normalize_source_order(["thermal", "thermal", "solar"]) == (
        "thermal",
        "solar",
        "hydro",
        "wind",
    )
