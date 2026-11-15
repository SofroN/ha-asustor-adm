"""Загрузка чистых модулей интеграции без импорта пакета целиком.

`custom_components/asustor_adm/__init__.py` связывает интеграцию с Home
Assistant, поэтому обычный импорт любого подмодуля тянет весь HA. Для
быстрых тестов регистрируем облегчённый родительский пакет: подмодули
загружаются из настоящих файлов, а `__init__.py` не выполняется.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import types

PACKAGE = "custom_components.asustor_adm"
PACKAGE_DIR = pathlib.Path(__file__).parents[2] / "custom_components" / "asustor_adm"


def _register_light_package() -> None:
    """Зарегистрировать родительские пакеты без выполнения их `__init__`."""
    if PACKAGE in sys.modules:
        return
    root = types.ModuleType("custom_components")
    root.__path__ = [str(PACKAGE_DIR.parent)]
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules["custom_components"] = root
    sys.modules[PACKAGE] = package


_register_light_package()


def import_module(name: str):
    """Импортировать подмодуль интеграции, минуя `__init__.py` пакета."""
    _register_light_package()
    return importlib.import_module(f"{PACKAGE}.{name}")
