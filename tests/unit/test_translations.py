"""Согласованность строк интерфейса и переводов."""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

COMPONENT = pathlib.Path(__file__).parents[2] / "custom_components" / "asustor_adm"

# Кириллица в исходнике строк означает, что английский интерфейс покажет русский
# текст: strings.json — источник перевода en.json, а не наоборот.
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")


def _keys(payload: Any, prefix: str = "") -> set[str]:
    """Собрать полные пути ключей вложенного JSON-объекта."""
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            keys.update(_keys(value, path))
    return keys


def _load(name: str) -> dict[str, Any]:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def _texts(payload: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Собрать все строковые значения с путями ключей."""
    found: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(_texts(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(payload, str):
        found.append((prefix, payload))
    return found


def test_english_translation_matches_strings() -> None:
    """Перевод en.json повторяет строки интерфейса один в один."""
    assert _load("translations/en.json") == _load("strings.json")


def test_english_source_has_no_russian_text() -> None:
    """Английский исходник и его перевод не содержат русского текста."""
    for name in ("strings.json", "translations/en.json"):
        offenders = [key for key, text in _texts(_load(name)) if _CYRILLIC.search(text)]
        assert offenders == [], f"русский текст в {name}: {offenders}"


def test_russian_translation_has_same_keys() -> None:
    """Русский перевод содержит те же ключи, что и строки интерфейса."""
    source = _keys(_load("strings.json"))
    russian = _keys(_load("translations/ru.json"))
    assert source - russian == set(), "в ru.json не хватает ключей"
    assert russian - source == set(), "в ru.json есть лишние ключи"


def test_entity_names_are_unique() -> None:
    """Имена сущностей внутри платформы не повторяются."""
    strings = _load("strings.json")
    for platform in ("sensor", "binary_sensor", "button", "update"):
        names = [
            description.get("name")
            for description in strings["entity"][platform].values()
            if "name" in description
        ]
        assert len(names) == len(set(names)), f"повтор имён в {platform}"
