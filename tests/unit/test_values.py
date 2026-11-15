"""Проверки преобразования значений (задача 2.4)."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.asustor_adm.values import (
    bytes_to_gib,
    kb_to_mib,
    ratio_percent,
    to_flag,
    to_number,
    version_is_newer,
)


def test_to_number_strips_trailing_newline() -> None:
    """Строка с завершающим переводом строки даёт корректное число."""
    assert to_number("2.22\n") == 2.22
    assert to_number(" 1672376 ") == 1672376
    assert to_number("") is None
    assert to_number(None) is None
    assert to_number(True) is None


def test_kb_to_mib_uses_captured_value() -> None:
    """Память переводится из килобайт в мебибайты."""
    assert kb_to_mib(1983612) == 1937.1
    assert kb_to_mib("693264") == 677.0


def test_bytes_to_gib_uses_captured_value() -> None:
    """Объём тома переводится из байт в гибибайты."""
    assert bytes_to_gib(7932738306048) == 7387.94
    assert bytes_to_gib(1963301756928) == 1828.47


def test_ratio_percent_handles_zero_total() -> None:
    """Доля не вычисляется при нулевом или отсутствующем общем объёме."""
    assert ratio_percent(5, 10) == 50.0
    assert ratio_percent(5, 0) is None
    assert ratio_percent(None, 10) is None


def test_to_flag_handles_heterogeneous_values() -> None:
    """Признаки ADM приводятся к булеву значению в разных форматах."""
    assert to_flag(1) is True
    assert to_flag(0) is False
    assert to_flag(True) is True
    assert to_flag("TRUE") is True
    assert to_flag("false") is False
    assert to_flag("") is None
    assert to_flag(None) is None


@pytest.mark.parametrize(
    ("candidate", "reference", "expected"),
    [
        ("5.1.5.RN11", "5.1.4.RM62", True),
        ("5.1.4.RM62", "5.1.4.RM62", False),
        ("5.1.3.RN1", "5.1.4.RM62", False),
        ("RN11", "RM62", True),
        ("10.0", "9.9", True),
        ("5.1.4", "5.1.4.RM62", False),
        ("5.1.4.rm62", "5.1.4.RM62", False),
        (" 5.1.5.RN11 ", "5.1.4.RM62", True),
    ],
)
def test_version_is_newer_compares_segments(
    candidate: str, reference: str, expected: bool
) -> None:
    """Сегменты версий сравниваются числами и строками без учёта регистра."""
    assert version_is_newer(candidate, reference) is expected


@pytest.mark.parametrize(
    ("candidate", "reference"),
    [
        ("", "5.1.4.RM62"),
        (None, "5.1.4.RM62"),
        ("5.1.4.RM62", None),
        ("unknown", "5.1.4.RM62"),
        ("5.1.4.", "5.1.4.RM62"),
        ("5.1.4.2", "5.1.4.RM62"),
    ],
)
def test_version_is_newer_reports_incomparable(candidate: Any, reference: Any) -> None:
    """Непригодная версия и разнотипные сегменты не дают подтверждения."""
    assert version_is_newer(candidate, reference) is None
