"""Проверки единого источника версии — файла ``VERSION``.

Манифест читает HACS, ``pyproject.toml`` — сборка, поэтому расхождение
между ними ловится здесь, а не в момент установки у пользователя.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import tomllib

import pytest

ROOT = pathlib.Path(__file__).parents[2]
VERSION_FILE = ROOT / "VERSION"
MANIFEST = ROOT / "custom_components" / "asustor_adm" / "manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"


def _load_bump_module():
    """Загрузить скрипт версии как модуль, не заводя отдельный пакет."""
    path = ROOT / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = _load_bump_module()


@pytest.fixture()
def tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """Копия файлов версии: запись проверяется без риска для репозитория."""
    component = tmp_path / "custom_components" / "asustor_adm"
    component.mkdir(parents=True)
    shutil.copy(MANIFEST, component / "manifest.json")
    shutil.copy(PYPROJECT, tmp_path / "pyproject.toml")
    shutil.copy(CHANGELOG, tmp_path / "CHANGELOG.md")
    shutil.copy(VERSION_FILE, tmp_path / "VERSION")
    return tmp_path


def _read_changelog(tree_path: pathlib.Path) -> str:
    return (tree_path / "CHANGELOG.md").read_text(encoding="utf-8")


def test_version_file_is_single_semver_line() -> None:
    """Файл VERSION содержит ровно одну строку X.Y.Z без префикса v."""
    lines = VERSION_FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert not lines[0].startswith("v")
    bump_version.parse_semver(lines[0])


def test_manifest_version_matches_version_file() -> None:
    """Версия в манифесте совпадает с файлом VERSION."""
    current = bump_version.read_version(ROOT)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == current


def test_pyproject_version_matches_version_file() -> None:
    """Версия в pyproject.toml совпадает с файлом VERSION."""
    current = bump_version.read_version(ROOT)
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == current


def test_changelog_has_unreleased_and_current_section() -> None:
    """CHANGELOG содержит пустой раздел будущих изменений и раздел версии."""
    current = bump_version.read_version(ROOT)
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "## [Unreleased]" in text
    assert f"## [{current}]" in text
    # Заголовок версии дополняется датой выпуска в формате ISO.
    assert bump_version.changelog_notes(text, current)


def test_changelog_links_cover_unreleased_and_current() -> None:
    """Ссылки сравнения и релиза описаны для Unreleased и текущей версии."""
    current = bump_version.read_version(ROOT)
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "[Unreleased]: " in text and "/compare/" in text
    assert f"[{current}]: " in text and "/releases/tag/" in text


@pytest.mark.parametrize(
    ("level", "current", "expected"),
    [
        ("patch", "0.1.0", "0.1.1"),
        ("minor", "0.1.0", "0.2.0"),
        ("major", "0.1.0", "1.0.0"),
        ("patch", "1.2.3", "1.2.4"),
        ("minor", "1.2.3", "1.3.0"),
        ("major", "1.2.3", "2.0.0"),
    ],
)
def test_bump_increments_requested_part(
    level: str, current: str, expected: str
) -> None:
    """Инкремент поднимает запрошенную часть и обнуляет младшие."""
    assert bump_version.bump(current, level) == expected


def test_bump_rejects_unknown_level() -> None:
    """Неизвестный уровень инкремента — ошибка, а не тихий patch."""
    with pytest.raises(bump_version.VersionError):
        bump_version.bump("0.1.0", "hotfix")


@pytest.mark.parametrize(
    "text", ["", "v0.1.0", "0.1", "0.1.0.1", "01.0.0", "0.1.0-rc1", "1.0.0+build"]
)
def test_parse_semver_rejects_invalid(text: str) -> None:
    """Строгий SemVer без префикса v, ведущих нулей и суффиксов."""
    with pytest.raises(bump_version.VersionError):
        bump_version.parse_semver(text)


def test_set_version_updates_every_file(tree: pathlib.Path) -> None:
    """Запись версии обновляет VERSION, манифест и pyproject.toml."""
    bump_version.set_version(tree, "1.2.3")
    assert (tree / "VERSION").read_text(encoding="utf-8") == "1.2.3\n"
    manifest = json.loads(
        (tree / "custom_components" / "asustor_adm" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["version"] == "1.2.3"
    assert manifest["domain"] == "asustor_adm"
    pyproject = tomllib.loads((tree / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "1.2.3"


def test_cli_dry_run_keeps_files_untouched(tree: pathlib.Path) -> None:
    """Прогон с --dry-run печатает версию, но файлы не меняет."""
    before = {
        path.name: path.read_bytes() for path in tree.rglob("*") if path.is_file()
    }
    assert bump_version.main(["--level", "patch", "--dry-run"], root=tree) == 0
    after = {path.name: path.read_bytes() for path in tree.rglob("*") if path.is_file()}
    assert before == after
    assert bump_version.read_version(tree) == "0.1.0"


def test_cli_release_writes_version_and_changelog(tree: pathlib.Path) -> None:
    """Выпуск обновляет версию, добавляет раздел и переписывает ссылки."""
    code = bump_version.main(["--level", "minor", "--today", "2026-12-31"], root=tree)
    assert code == 0
    assert bump_version.read_version(tree) == "0.2.0"
    text = _read_changelog(tree)
    assert "## [0.2.0] - 2026-12-31" in text
    assert "## [Unreleased]" in text
    assert "/compare/v0.2.0...HEAD" in text
    assert "[0.2.0]: " in text
    # Раздел текущей версии остаётся на месте и не дублируется.
    assert text.count("## [0.1.0]") == 1


def test_promote_changelog_rejects_existing_version() -> None:
    """Повторный выпуск той же версии запрещён: раздел уже есть."""
    current = bump_version.read_version(ROOT)
    text = CHANGELOG.read_text(encoding="utf-8")
    with pytest.raises(bump_version.VersionError):
        bump_version.promote_changelog(text, current, "2026-12-31")


def test_changelog_notes_returns_only_version_body() -> None:
    """Тело релиза — содержимое раздела без заголовка и без ссылок."""
    notes = bump_version.changelog_notes(
        CHANGELOG.read_text(encoding="utf-8"),
        bump_version.read_version(ROOT),
    )
    assert notes.startswith("### ")
    assert "## [" not in notes
    assert "]:" not in notes


def test_changelog_notes_rejects_empty_section(tree: pathlib.Path) -> None:
    """Выпуск без записей в CHANGELOG не даёт пустого текста релиза."""
    assert bump_version.main(["--level", "patch"], root=tree) == 0
    text = _read_changelog(tree)
    with pytest.raises(bump_version.VersionError):
        bump_version.changelog_notes(text, bump_version.read_version(tree))
