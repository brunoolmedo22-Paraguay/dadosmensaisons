import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def load_preserve_date_state():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "preserve_date_state"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    fake_streamlit = SimpleNamespace(session_state={})
    namespace = {"st": fake_streamlit, "pd": pd, "date": date}
    exec(compile(module, str(APP_PATH), "exec"), namespace)
    return namespace["preserve_date_state"], fake_streamlit.session_state


def test_keeps_previous_date_when_it_remains_in_bounds() -> None:
    preserve_date_state, state = load_preserve_date_state()
    state["chart_start_daily"] = date(2025, 4, 10)

    value = preserve_date_state(
        "chart_start_daily",
        default=date(2026, 1, 1),
        min_value=date(2020, 1, 1),
        max_value=date(2026, 12, 31),
    )

    assert value == date(2025, 4, 10)
    assert state["chart_start_daily"] == date(2025, 4, 10)


def test_clamps_date_only_when_new_bounds_require_it() -> None:
    preserve_date_state, state = load_preserve_date_state()
    state["analysis_start_date"] = date(2010, 1, 1)

    value = preserve_date_state(
        "analysis_start_date",
        default=date(2025, 1, 1),
        min_value=date(2020, 1, 1),
        max_value=date(2026, 12, 31),
    )

    assert value == date(2020, 1, 1)
    assert state["analysis_start_date"] == date(2020, 1, 1)
