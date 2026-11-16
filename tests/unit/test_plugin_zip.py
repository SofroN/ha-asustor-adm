"""Проверки архива плагина: состав, воспроизводимость, проверка версии.

Архив — то, что пользователь распаковывает в ``/config``, поэтому тест
фиксирует структуру ``custom_components/asustor_adm/...`` и отсутствие
мусора среды исполнения.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).parents[2]
PREFIX = "custom_components/asustor_adm/"


def _load_plugin_zip():
    """Загрузить скрипт сборки как модуль, не заводя отдельный пакет."""
    path = ROOT / "scripts" / "build_plugin_zip.py"
    spec = importlib.util.spec_from_file_location("build_plugin_zip", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass(slots=True) ищет модуль в sys.modules: регистрируем заранее.
    sys.modules["build_plugin_zip"] = module
    spec.loader.exec_module(module)
    return module


plugin_zip = _load_plugin_zip()


@pytest.fixture()
def tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """Каталог плагина с файлами и мусором, который в архив не входит."""
    component = tmp_path / "custom_components" / "asustor_adm"
    (component / "translations").mkdir(parents=True)
    (component / "__pycache__").mkdir()
    (component / "manifest.json").write_text(
        json.dumps({"domain": "asustor_adm", "version": "1.2.3"}),
        encoding="utf-8",
    )
    (component / "__init__.py").write_text("", encoding="utf-8")
    (component / "translations" / "en.json").write_text("{}", encoding="utf-8")
    (component / "__pycache__" / "sensor.cpython-312.pyc").write_bytes(b"junk")
    (component / "leftover.pyc").write_bytes(b"junk")
    (component / ".DS_Store").write_bytes(b"junk")
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    return tmp_path


def test_archive_keeps_home_assistant_layout(tree: pathlib.Path) -> None:
    """В архиве структура /config: custom_components/asustor_adm и только файлы."""
    out = plugin_zip.build_archive(tree, tree / "dist" / "asustor_adm-1.2.3.zip")
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
    assert PREFIX + "manifest.json" in names
    assert PREFIX + "__init__.py" in names
    assert PREFIX + "translations/en.json" in names
    assert not [name for name in names if "__pycache__" in name]
    assert not [name for name in names if name.endswith((".pyc", ".DS_Store"))]


def test_archive_is_reproducible(tree: pathlib.Path) -> None:
    """Две сборки одного дерева дают побайтово одинаковый архив."""
    first = plugin_zip.build_archive(tree, tree / "dist" / "first.zip")
    second = plugin_zip.build_archive(tree, tree / "dist" / "second.zip")
    assert first.read_bytes() == second.read_bytes()


def test_archive_rejects_version_mismatch(tree: pathlib.Path) -> None:
    """Версия архива должна совпадать с manifest.json, иначе установка сломается."""
    with pytest.raises(plugin_zip.ArchiveError):
        plugin_zip.build_archive(tree, tree / "dist" / "wrong.zip", "2.0.0")


def test_manifest_without_version_is_rejected(tree: pathlib.Path) -> None:
    """Манифест без версии не даёт собрать архив."""
    manifest = tree / "custom_components" / "asustor_adm" / "manifest.json"
    manifest.write_text(json.dumps({"domain": "asustor_adm"}), encoding="utf-8")
    with pytest.raises(plugin_zip.ArchiveError):
        plugin_zip.build_archive(tree, tree / "dist" / "broken.zip")


def test_cli_prints_archive_path(
    tree: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI печатает путь архива в stdout: его забирает workflow."""
    out = tree / "dist" / "asustor_adm-1.2.3.zip"
    assert plugin_zip.main(["--root", str(tree), "--out", str(out)]) == 0
    assert capsys.readouterr().out.strip() == str(out)
    assert out.is_file()


def test_repository_archive_matches_version(tmp_path: pathlib.Path) -> None:
    """Архив рабочего репозитория содержит манифест текущей версии."""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    out = plugin_zip.build_archive(ROOT, tmp_path / "asustor_adm.zip")
    with zipfile.ZipFile(out) as archive:
        manifest = json.loads(archive.read(PREFIX + "manifest.json"))
        names = archive.namelist()
    assert manifest["version"] == version
    assert PREFIX + "translations/ru.json" in names
    assert PREFIX + "brand/icon.png" in names
