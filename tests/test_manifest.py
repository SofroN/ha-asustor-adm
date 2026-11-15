"""Проверки файлов каркаса интеграции (задача 1.1)."""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "asustor_adm"
REQUIRED_MANIFEST_KEYS = ("domain", "config_flow", "iot_class", "version")


def test_manifest_has_required_keys() -> None:
    """Манифест содержит обязательные ключи и корректные значения."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    for key in REQUIRED_MANIFEST_KEYS:
        assert key in manifest, f"в manifest.json нет ключа {key}"
    assert manifest["domain"] == "asustor_adm"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert manifest["integration_type"] == "device"
    assert manifest["codeowners"] == ["@SofroN"]
    assert manifest["documentation"].endswith("/ha-asustor-adm")
    assert "requirements" not in manifest or manifest["requirements"] == []


def test_hacs_manifest_has_required_keys() -> None:
    """Файл hacs.json разбирается и содержит имя и версию Home Assistant."""
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["name"] == "ASUSTOR NAS (ADM)"
    assert "homeassistant" in hacs


def test_component_files_exist() -> None:
    """В каталоге интеграции присутствуют обязательные файлы и переводы."""
    for name in (
        "__init__.py",
        "manifest.json",
        "const.py",
        "config_flow.py",
        "diagnostics.py",
        "translations/en.json",
        "translations/ru.json",
        "brand/icon.png",
    ):
        assert (COMPONENT / name).exists(), f"нет файла {name}"
    assert (ROOT / "README.md").exists()


def test_strings_and_translations_are_valid_json() -> None:
    """Строки интерфейса и переводы разбираются как JSON."""
    for path in (
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "translations" / "ru.json",
    ):
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
