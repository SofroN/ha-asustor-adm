"""Преобразование значений из ответов ADM."""

from __future__ import annotations

from typing import Any, Final

KIB_IN_MIB: Final = 1024.0
BYTES_IN_GIB: Final = 1024.0**3
PERCENT: Final = 100.0

_TRUE_STRINGS: Final = frozenset({"true", "yes", "on", "enabled"})
_FALSE_STRINGS: Final = frozenset({"false", "no", "off", "disabled"})


def to_number(value: Any) -> float | None:
    """Привести значение ADM к числу, отбросив пробелы и переводы строк."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    """Привести значение ADM к целому числу."""
    number = to_number(value)
    if number is None:
        return None
    return int(number)


def to_text(value: Any) -> str | None:
    """Привести значение ADM к непустой строке."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def to_flag(value: Any) -> bool | None:
    """Привести разнородный признак ADM к булеву значению."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        if text in _TRUE_STRINGS:
            return True
        if text in _FALSE_STRINGS:
            return False
        number = to_number(text)
        return bool(int(number)) if number is not None else None
    return None


def kb_to_mib(value: Any) -> float | None:
    """Перевести килобайты в мебибайты с округлением до целых."""
    number = to_number(value)
    if number is None:
        return None
    return round(number / KIB_IN_MIB, 1)


def bytes_to_gib(value: Any) -> float | None:
    """Перевести байты в гибибайты с двумя знаками после запятой."""
    number = to_number(value)
    if number is None:
        return None
    return round(number / BYTES_IN_GIB, 2)


def ratio_percent(part: Any, total: Any) -> float | None:
    """Вычислить долю одной величины от другой в процентах."""
    part_number = to_number(part)
    total_number = to_number(total)
    if part_number is None or total_number is None or total_number <= 0:
        return None
    return round(part_number / total_number * PERCENT, 1)
