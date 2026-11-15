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


def _version_segments(value: Any) -> tuple[str, ...] | None:
    """Разбить версию ADM на сегменты, отбросив пробелы вокруг них.

    Версия без цифр и с пустым сегментом считается непригодной для сравнения:
    подтвердить по ней обновление нельзя.
    """
    text = to_text(value)
    if text is None or not any(character.isdigit() for character in text):
        return None
    segments = tuple(part.strip() for part in text.split("."))
    if any(not segment for segment in segments):
        return None
    return segments


def _compare_segment(candidate: str, reference: str) -> int | None:
    """Сравнить сегменты версии: 1 — кандидат больше, 0 — равны, -1 — меньше.

    Разнотипные сегменты (число и строка) не сравниваются: пропустить
    обновление лучше, чем объявить его без достаточного основания.
    """
    if candidate.isdigit() and reference.isdigit():
        left, right = int(candidate), int(reference)
    elif candidate.isdigit() or reference.isdigit():
        return None
    else:
        left, right = candidate.lower(), reference.lower()
    if left == right:
        return 0
    return 1 if left > right else -1


def version_is_newer(candidate: Any, reference: Any) -> bool | None:
    """Сказать, новее ли версия ADM ``candidate``, чем ``reference``.

    Сегменты делятся по точкам и сравниваются слева направо: сегмент из цифр —
    как число, иначе — как строка без учёта регистра. Версия, являющаяся
    префиксом другой (``5.1.4`` против ``5.1.4.RM62``), не считается новее.
    Пустое значение, отсутствие цифр и разнотипные сегменты дают ``None``:
    версии не сравнимы, и обновление не подтверждается.
    """
    candidate_segments = _version_segments(candidate)
    reference_segments = _version_segments(reference)
    if candidate_segments is None or reference_segments is None:
        return None
    for left, right in zip(candidate_segments, reference_segments, strict=False):
        result = _compare_segment(left, right)
        if result is None:
            return None
        if result:
            return result > 0
    return False
