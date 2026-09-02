from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Final

import pandas as pd


SUBSYSTEM_NAMES: Final[dict[int, str]] = {
    1: "Sudeste/Centro-Oeste",
    2: "Sul",
    3: "Nordeste",
    4: "Norte",
    11: "NOFICT1",
}

SOURCE_KEY_BY_LABEL: Final[dict[str, str]] = {
    "PCH": "pch_central_mwmed",
    "PCT": "thermal_central_mwmed",
    "EOL": "wind_central_mwmed",
    "UFV": "solar_central_mwmed",
    "PCH MMGD": "pch_mmgd_mwmed",
    "PCT MMGD": "thermal_mmgd_mwmed",
    "EOL MMGD": "wind_mmgd_mwmed",
    "UFV MMGD": "solar_mmgd_mwmed",
}

SUMMARY_SOURCE_COLUMNS: Final[tuple[str, ...]] = tuple(SOURCE_KEY_BY_LABEL.values())
MMGD_COLUMNS: Final[tuple[str, ...]] = (
    "pch_mmgd_mwmed",
    "thermal_mmgd_mwmed",
    "wind_mmgd_mwmed",
    "solar_mmgd_mwmed",
)


class SistemaDatError(ValueError):
    """Raised when a file cannot be recognized as a usable NEWAVE sistema.dat."""


@dataclass
class SistemaDatData:
    monthly_summary: pd.DataFrame
    market: pd.DataFrame
    nonsimulated_generation: pd.DataFrame
    interchanges: pd.DataFrame
    deficit_costs: pd.DataFrame
    deficit_tiers: int
    warnings: tuple[str, ...]
    encoding: str


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.upper().split())


def _decode(raw: bytes | str) -> tuple[str, str]:
    if isinstance(raw, str):
        return raw, "text"
    if not raw:
        raise SistemaDatError("O arquivo está vazio.")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise SistemaDatError("Não foi possível decodificar o arquivo de texto.")


def _section_index(lines: list[str], title: str) -> int | None:
    target = _plain(title)
    for index, line in enumerate(lines):
        if _plain(line) == target:
            return index
    return None


def _is_year_line(line: str) -> bool:
    return len(line) >= 4 and line[:4].isdigit() and 1900 <= int(line[:4]) <= 2300


def _monthly_values(line: str) -> list[tuple[int, float]]:
    """Read the twelve official 8-character fields beginning at column 7."""
    padded = line.rstrip("\r\n").ljust(102)
    parsed: list[tuple[int, float]] = []
    for month in range(1, 13):
        start = 6 + (month - 1) * 8
        token = padded[start : start + 8].strip()
        if not token:
            continue
        try:
            parsed.append((month, float(token.replace(",", "."))))
        except ValueError as exc:
            raise SistemaDatError(
                f"Valor mensal inválido no ano {line[:4]}, mês {month}: {token!r}."
            ) from exc
    return parsed


def _parse_market(lines: list[str]) -> pd.DataFrame:
    start = _section_index(lines, "MERCADO DE ENERGIA TOTAL")
    if start is None:
        raise SistemaDatError("Bloco MERCADO DE ENERGIA TOTAL não encontrado.")

    rows: list[dict[str, object]] = []
    subsystem_code: int | None = None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped == "999":
            break
        if re.fullmatch(r"\d{1,3}", stripped or ""):
            subsystem_code = int(stripped)
            continue
        if not _is_year_line(line):
            continue
        if subsystem_code is None:
            raise SistemaDatError("Ano de mercado encontrado sem subsistema associado.")
        year = int(line[:4])
        for month, value in _monthly_values(line):
            rows.append(
                {
                    "date": pd.Timestamp(year=year, month=month, day=1),
                    "subsystem_code": subsystem_code,
                    "subsystem": SUBSYSTEM_NAMES.get(subsystem_code, f"Subsistema {subsystem_code}"),
                    "market_mwmed": value,
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SistemaDatError("O bloco de mercado não contém valores mensais válidos.")
    return frame.sort_values(["date", "subsystem_code"], kind="stable").reset_index(drop=True)


def _parse_nonsimulated_generation(lines: list[str]) -> pd.DataFrame:
    start = _section_index(lines, "GERACAO DE USINAS NAO SIMULADAS")
    if start is None:
        raise SistemaDatError("Bloco GERACAO DE USINAS NAO SIMULADAS não encontrado.")

    rows: list[dict[str, object]] = []
    current: tuple[int, int, str] | None = None
    header_pattern = re.compile(r"^\s*(\d{1,3})\s+(\d{1,3})\s+([A-Za-z][A-Za-z ]*?)\s*$")
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped == "999":
            break
        header_match = header_pattern.match(line)
        if header_match and not _is_year_line(line):
            subsystem_code = int(header_match.group(1))
            block_code = int(header_match.group(2))
            source_label = _plain(header_match.group(3))
            current = (subsystem_code, block_code, source_label)
            continue
        if not _is_year_line(line):
            continue
        if current is None:
            raise SistemaDatError("Ano de geração não simulada encontrado sem fonte associada.")
        subsystem_code, block_code, source_label = current
        source_key = SOURCE_KEY_BY_LABEL.get(source_label)
        year = int(line[:4])
        for month, value in _monthly_values(line):
            rows.append(
                {
                    "date": pd.Timestamp(year=year, month=month, day=1),
                    "subsystem_code": subsystem_code,
                    "subsystem": SUBSYSTEM_NAMES.get(subsystem_code, f"Subsistema {subsystem_code}"),
                    "block_code": block_code,
                    "source": source_label,
                    "source_key": source_key or source_label.lower().replace(" ", "_"),
                    "is_mmgd": "MMGD" in source_label,
                    "generation_mwmed": value,
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SistemaDatError("O bloco de geração não simulada não contém valores mensais válidos.")
    return frame.sort_values(
        ["date", "subsystem_code", "block_code"], kind="stable"
    ).reset_index(drop=True)


def _parse_interchanges(lines: list[str]) -> pd.DataFrame:
    start = _section_index(lines, "LIMITES DE INTERCAMBIO")
    if start is None:
        return pd.DataFrame(
            columns=[
                "date",
                "origin_code",
                "origin",
                "destination_code",
                "destination",
                "limit_mw",
                "is_unbounded",
            ]
        )

    rows: list[dict[str, object]] = []
    pair: tuple[int, int] | None = None
    direction = 0
    years_in_direction = 0
    last_year: int | None = None
    pair_pattern = re.compile(r"^\s*(\d{1,3})\s+(\d{1,3})\s+(\d+)\s*$")

    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped == "999":
            break
        pair_match = pair_pattern.match(line)
        if pair_match and not _is_year_line(line):
            pair = (int(pair_match.group(1)), int(pair_match.group(2)))
            direction = 0
            years_in_direction = 0
            last_year = None
            continue
        if not stripped:
            if pair is not None and direction == 0 and years_in_direction:
                direction = 1
                years_in_direction = 0
                last_year = None
            continue
        if not _is_year_line(line):
            continue
        if pair is None:
            raise SistemaDatError("Ano de intercâmbio encontrado sem par de subsistemas.")

        year = int(line[:4])
        # Some generators omit the blank separator between directions. A
        # repeated or decreasing year identifies the beginning of B -> A.
        if direction == 0 and last_year is not None and year <= last_year:
            direction = 1
            years_in_direction = 0
        origin_code, destination_code = pair if direction == 0 else (pair[1], pair[0])
        for month, value in _monthly_values(line):
            rows.append(
                {
                    "date": pd.Timestamp(year=year, month=month, day=1),
                    "origin_code": origin_code,
                    "origin": SUBSYSTEM_NAMES.get(origin_code, f"Subsistema {origin_code}"),
                    "destination_code": destination_code,
                    "destination": SUBSYSTEM_NAMES.get(
                        destination_code, f"Subsistema {destination_code}"
                    ),
                    "limit_mw": value,
                    "is_unbounded": value >= 99999.0,
                }
            )
        years_in_direction += 1
        last_year = year

    columns = [
        "date",
        "origin_code",
        "origin",
        "destination_code",
        "destination",
        "limit_mw",
        "is_unbounded",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["origin_code", "destination_code", "date"], kind="stable"
    ).reset_index(drop=True)


def _parse_deficit(lines: list[str]) -> tuple[int, pd.DataFrame]:
    tier_start = _section_index(lines, "NUMERO DE PATAMARES DE DEFICIT")
    cost_start = _section_index(lines, "CUSTO DO DEFICIT")
    tiers = 0
    if tier_start is not None:
        for line in lines[tier_start + 1 :]:
            stripped = line.strip()
            if stripped.isdigit():
                tiers = int(stripped)
                break

    columns = ["subsystem_code", "subsystem", "is_fictitious"]
    columns += [f"deficit_cost_tier_{tier}" for tier in range(1, tiers + 1)]
    columns += [f"cut_fraction_tier_{tier}" for tier in range(1, tiers + 1)]
    if cost_start is None:
        return tiers, pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for line in lines[cost_start + 1 :]:
        stripped = line.strip()
        if stripped == "999":
            break
        code_field = line[0:3].strip()
        name_field = line[4:15].strip()
        flag_field = line[15:18].strip()
        if not code_field.isdigit() or flag_field not in {"0", "1"}:
            continue
        subsystem_code = int(code_field)
        row: dict[str, object] = {
            "subsystem_code": subsystem_code,
            "subsystem": SUBSYSTEM_NAMES.get(subsystem_code, name_field),
            "is_fictitious": flag_field == "1",
        }
        numeric_values: list[float] = []
        for token in line[18:].split():
            try:
                numeric_values.append(float(token.replace(",", ".")))
            except ValueError:
                numeric_values.append(float("nan"))
        # The NEWAVE record always reserves four cost fields followed by four
        # cut-fraction fields, even when only one deficit tier is active.
        for tier in range(1, tiers + 1):
            row[f"deficit_cost_tier_{tier}"] = (
                numeric_values[tier - 1] if len(numeric_values) >= tier else float("nan")
            )
            cut_index = 4 + tier - 1
            row[f"cut_fraction_tier_{tier}"] = (
                numeric_values[cut_index]
                if len(numeric_values) > cut_index
                else float("nan")
            )
        rows.append(row)
    return tiers, pd.DataFrame(rows, columns=columns)


def _build_monthly_summary(
    market: pd.DataFrame,
    generation: pd.DataFrame,
) -> pd.DataFrame:
    real_market = market.loc[market["subsystem_code"].isin((1, 2, 3, 4))]
    market_sin = (
        real_market.groupby("date", as_index=True)["market_mwmed"]
        .sum(min_count=1)
        .rename("market_sin_mwmed")
    )

    real_generation = generation.loc[generation["subsystem_code"].isin((1, 2, 3, 4))]
    source_summary = real_generation.pivot_table(
        index="date",
        columns="source_key",
        values="generation_mwmed",
        aggfunc="sum",
    )
    summary = market_sin.to_frame().join(source_summary, how="outer").sort_index()
    for column in SUMMARY_SOURCE_COLUMNS:
        if column not in summary.columns:
            summary[column] = 0.0
        summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0.0)
    summary["mmgd_total_mwmed"] = summary[list(MMGD_COLUMNS)].sum(axis=1)
    summary["global_load_mwmed"] = (
        summary["market_sin_mwmed"] + summary["mmgd_total_mwmed"]
    )
    summary.index.name = "date"
    return summary.reset_index()


def parse_sistema_dat(raw: bytes | str) -> SistemaDatData:
    text, encoding = _decode(raw)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any("MERCADO DE ENERGIA TOTAL" in _plain(line) for line in lines):
        raise SistemaDatError(
            "O conteúdo não corresponde a um sistema.dat reconhecível do NEWAVE."
        )

    market = _parse_market(lines)
    generation = _parse_nonsimulated_generation(lines)
    interchanges = _parse_interchanges(lines)
    deficit_tiers, deficit_costs = _parse_deficit(lines)
    monthly_summary = _build_monthly_summary(market, generation)

    warnings: list[str] = []
    expected_subsystems = {1, 2, 3, 4}
    found_subsystems = set(market["subsystem_code"].unique())
    missing = sorted(expected_subsystems - found_subsystems)
    if missing:
        warnings.append("Subsistemas de mercado ausentes: " + ", ".join(map(str, missing)) + ".")
    unknown_sources = sorted(
        set(generation["source"].unique()) - set(SOURCE_KEY_BY_LABEL)
    )
    if unknown_sources:
        warnings.append("Fontes não mapeadas: " + ", ".join(unknown_sources) + ".")
    if interchanges.empty:
        warnings.append("O arquivo não contém limites de intercâmbio utilizáveis.")

    return SistemaDatData(
        monthly_summary=monthly_summary,
        market=market,
        nonsimulated_generation=generation,
        interchanges=interchanges,
        deficit_costs=deficit_costs,
        deficit_tiers=deficit_tiers,
        warnings=tuple(warnings),
        encoding=encoding,
    )
