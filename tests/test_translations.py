"""Согласованность строк интерфейса и переводов."""

from __future__ import annotations

import json
import pathlib
from typing import Any

COMPONENT = pathlib.Path(__file__).parents[1] / "custom_components" / "asustor_adm"


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


def test_english_translation_matches_strings() -> None:
    """Перевод en.json повторяет строки интерфейса один в один."""
    assert _load("translations/en.json") == _load("strings.json")


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
