"""Проверки единого источника версии — файла ``VERSION``.

Манифест читает HACS, ``pyproject.toml`` — сборка, поэтому расхождение
между ними ловится здесь, а не в момент установки у пользователя.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
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
    # dataclass(slots=True) ищет модуль в sys.modules: регистрируем заранее.
    sys.modules["bump_version"] = module
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
    current = bump_version.read_version(tree)
    before = {
        path.name: path.read_bytes() for path in tree.rglob("*") if path.is_file()
    }
    assert bump_version.main(["--level", "patch", "--dry-run"], root=tree) == 0
    after = {path.name: path.read_bytes() for path in tree.rglob("*") if path.is_file()}
    assert before == after
    assert bump_version.read_version(tree) == current


def test_cli_release_writes_version_and_changelog(tree: pathlib.Path) -> None:
    """Выпуск обновляет версию, добавляет раздел и переписывает ссылки."""
    current = bump_version.read_version(tree)
    target = bump_version.bump(current, "minor")
    code = bump_version.main(["--level", "minor", "--today", "2026-12-31"], root=tree)
    assert code == 0
    assert bump_version.read_version(tree) == target
    text = _read_changelog(tree)
    assert f"## [{target}] - 2026-12-31" in text
    assert "## [Unreleased]" in text
    assert f"/compare/v{target}...HEAD" in text
    assert f"[{target}]: " in text
    # Раздел прошлой версии остаётся на месте и не дублируется.
    assert text.count(f"## [{current}]") == 1


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
    # Раздел будущих изменений заполняется по ходу работы, поэтому пустой
    # заголовок задаётся здесь явно, а не берётся из рабочего CHANGELOG.
    (tree / "CHANGELOG.md").write_text(
        "# История изменений\n"
        "\n"
        "## [Unreleased]\n"
        "\n"
        "## [0.1.0] - 2026-11-15\n"
        "\n"
        "### Добавлено\n"
        "\n"
        "- Интеграция.\n",
        encoding="utf-8",
    )
    assert bump_version.main(["--level", "patch"], root=tree) == 0
    text = _read_changelog(tree)
    with pytest.raises(bump_version.VersionError):
        bump_version.changelog_notes(text, bump_version.read_version(tree))


# --- Версия как событие выпуска: теги, решение, текст релиза -------------

_CHANGELOG_BASE = """# История изменений

## [Unreleased]

## [0.1.0] - 2026-11-15

### Добавлено

- Интеграция.

[Unreleased]: https://github.com/SofroN/ha-asustor-adm/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SofroN/ha-asustor-adm/releases/tag/v0.1.0
"""

_CHANGELOG_NEXT = """# История изменений

## [Unreleased]

## [0.2.0] - 2026-12-01

### Добавлено

- Новый сенсор.

## [0.1.0] - 2026-11-15

### Добавлено

- Интеграция.

[Unreleased]: https://github.com/SofroN/ha-asustor-adm/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SofroN/ha-asustor-adm/releases/tag/v0.2.0
[0.1.0]: https://github.com/SofroN/ha-asustor-adm/releases/tag/v0.1.0
"""


def _git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout


@pytest.fixture()
def repository(tmp_path: pathlib.Path) -> pathlib.Path:
    """Репозиторий с прошлым релизом и коммитами после него."""
    if shutil.which("git") is None:  # pragma: no cover - среда без git
        pytest.skip("для теста нужен git")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG_BASE, encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "feat: initial integration")
    _git(tmp_path, "tag", "-a", "v0.1.0", "-m", "v0.1.0")
    (tmp_path / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG_NEXT, encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "docs(changelog): describe 0.2.0")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "fix(api): verified contract")
    return tmp_path


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v0.1.0", (0, 1, 0)),
        ("0.1.0", None),
        ("v0.1", None),
        ("nightly", None),
        ("v1.0.0-rc1", None),
    ],
)
def test_parse_tag_accepts_only_version_tags(
    tag: str, expected: tuple[int, int, int] | None
) -> None:
    """Тег релиза — префикс v и полный SemVer; прочие теги не версии."""
    assert bump_version.parse_tag(tag) == expected


@pytest.mark.parametrize(
    ("tags", "version", "expected"),
    [
        (["v0.1.0", "v0.2.0", "nightly"], "0.3.0", "v0.2.0"),
        (["v0.1.0", "v1.0.0"], "0.9.0", "v0.1.0"),
        (["v0.1.0"], "0.1.0", None),
        ([], "0.1.0", None),
    ],
)
def test_previous_tag_is_latest_below_version(
    tags: list[str], version: str, expected: str | None
) -> None:
    """Предыдущий релиз — наибольший тег строго меньше выпускаемой версии."""
    assert bump_version.previous_tag(tags, version) == expected


def test_release_decision_publishes_new_version() -> None:
    """Новая версия выпускается и объясняет, после какого тега."""
    release, reason = bump_version.release_decision("0.2.0", ["v0.1.0"])
    assert release is True
    assert "v0.1.0" in reason


def test_release_decision_skips_existing_tag() -> None:
    """Существующий тег не перевыпускается: релиз уже опубликован."""
    release, reason = bump_version.release_decision("0.2.0", ["v0.1.0", "v0.2.0"])
    assert release is False
    assert "v0.2.0" in reason


def test_release_decision_rejects_downgrade() -> None:
    """Понижение версии — ошибка: релизы не отзываются автоматически."""
    with pytest.raises(bump_version.VersionError):
        bump_version.release_decision("0.1.5", ["v0.2.0"])


def test_sync_version_aligns_derived_files_only(tree: pathlib.Path) -> None:
    """Синхронизация правит производные файлы и не трогает CHANGELOG."""
    current = bump_version.read_version(tree)
    manifest = tree / "custom_components" / "asustor_adm" / "manifest.json"
    pyproject = tree / "pyproject.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(f'"{current}"', '"9.9.9"', 1),
        encoding="utf-8",
    )
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            f'version = "{current}"', 'version = "9.9.9"', 1
        ),
        encoding="utf-8",
    )
    changelog_before = _read_changelog(tree)
    version, changed = bump_version.sync_version(tree)
    assert version == current
    assert {path.name for path in changed} == {"manifest.json", "pyproject.toml"}
    assert _read_changelog(tree) == changelog_before
    # Повторная синхронизация ничего не меняет: коммит не появится.
    assert bump_version.sync_version(tree)[1] == []


def test_render_commits_groups_by_type() -> None:
    """Список изменений группируется по смыслу и сохраняет хеши."""
    commits = [
        bump_version.Commit(sha="a1", subject="feat(icons): explicit icons"),
        bump_version.Commit(sha="b2", subject="fix(api): keep contract"),
        bump_version.Commit(sha="c3", subject="ci: single workflow"),
        bump_version.Commit(sha="d4", subject="Update README"),
    ]
    text = bump_version.render_commits(commits)
    assert text.index("#### Добавлено") < text.index("#### Исправлено")
    assert text.index("#### Исправлено") < text.index("#### Служебное")
    assert text.index("#### Служебное") < text.index("#### Прочее")
    assert "`a1` feat(icons): explicit icons" in text
    assert "`d4` Update README" in text


def test_render_commits_returns_empty_for_no_commits() -> None:
    """Без коммитов блок не добавляется в текст релиза."""
    assert bump_version.render_commits([]) == ""


def test_changelog_notes_or_none_tolerates_missing_section() -> None:
    """В авторежиме отсутствие раздела версии не ломает сборку текста."""
    assert bump_version.changelog_notes_or_none(_CHANGELOG_BASE, "0.2.0") is None
    assert bump_version.changelog_notes_or_none(_CHANGELOG_BASE, "0.1.0") is not None


def test_release_body_uses_changelog_and_commits_since_previous(
    repository: pathlib.Path,
) -> None:
    """Текст релиза: раздел CHANGELOG, коммиты с прошлого тега и ссылка."""
    body = bump_version.release_body(repository, "0.2.0")
    assert "Новый сенсор." in body
    assert "### Коммиты v0.1.0...v0.2.0" in body
    assert "fix(api): verified contract" in body
    assert "docs(changelog): describe 0.2.0" in body
    assert "**Полный список изменений**: " in body
    assert "compare/v0.1.0...v0.2.0" in body
    assert "## [" not in body


def test_release_body_without_changelog_section_uses_commits(
    repository: pathlib.Path,
) -> None:
    """Без раздела CHANGELOG релиз всё равно описывает изменения."""
    changelog = repository / "CHANGELOG.md"
    changelog.write_text(
        _CHANGELOG_NEXT.split("## [0.2.0]")[0]
        + "[Unreleased]: https://github.com/SofroN/ha-asustor-adm/compare/"
        "v0.2.0...HEAD\n[0.2.0]: https://github.com/SofroN/ha-asustor-adm/"
        "releases/tag/v0.2.0\n[0.1.0]: https://github.com/SofroN/ha-asustor-adm/"
        "releases/tag/v0.1.0\n",
        encoding="utf-8",
    )
    body = bump_version.release_body(repository, "0.2.0")
    assert body.startswith("### Коммиты v0.1.0...v0.2.0")
    assert "fix(api): verified contract" in body


def test_git_commits_skip_release_commits(repository: pathlib.Path) -> None:
    """Служебный коммит выпуска не попадает в список изменений."""
    (repository / "VERSION").write_text("0.2.1\n", encoding="utf-8")
    _git(repository, "commit", "-q", "-am", "chore(release): v0.2.1")
    commits = bump_version.git_commits(repository, "v0.1.0..HEAD")
    assert not [item for item in commits if item.subject.startswith("chore(release)")]
    assert commits


def test_release_state_reports_new_version(repository: pathlib.Path) -> None:
    """Состояние выпуска описывает версию, тег и предыдущий релиз."""
    state = bump_version.release_state(repository)
    assert state["version"] == "0.2.0"
    assert state["tag"] == "v0.2.0"
    assert state["previous_tag"] == "v0.1.0"
    assert state["should_release"] is True


def test_release_state_skips_published_version(repository: pathlib.Path) -> None:
    """После установки тега повторного выпуска нет."""
    _git(repository, "tag", "-a", "v0.2.0", "-m", "v0.2.0")
    state = bump_version.release_state(repository)
    assert state["should_release"] is False
    assert state["previous_tag"] == "v0.1.0"


def test_cli_state_prints_json(
    repository: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--state печатает машиночитаемое решение о выпуске."""
    assert bump_version.main(["--state"], root=repository) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tag"] == "v0.2.0"
    assert payload["should_release"] is True


def test_cli_release_body_prints_notes(
    repository: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--release-body печатает готовый текст релиза для файла заметок."""
    assert bump_version.main(["--release-body", "0.2.0"], root=repository) == 0
    assert "### Коммиты v0.1.0...v0.2.0" in capsys.readouterr().out


def test_cli_sync_reports_changed_files(
    tree: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--sync печатает версию в stdout, а изменённые файлы — в stderr."""
    current = bump_version.read_version(tree)
    manifest = tree / "custom_components" / "asustor_adm" / "manifest.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(f'"{current}"', '"9.9.9"', 1),
        encoding="utf-8",
    )
    assert bump_version.main(["--sync"], root=tree) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == current
    assert "manifest.json" in captured.err
