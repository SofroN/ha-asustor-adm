"""Единое управление версией интеграции и текстом релиза.

Источник истины — файл ``VERSION`` в корне репозитория. ``manifest.json``
(его читает HACS) и ``pyproject.toml`` — производные: их обновляет этот
скрипт, а согласованность проверяет ``tests/unit/test_version.py``.

Режимы:

    python3 scripts/bump_version.py                      # текущая версия
    python3 scripts/bump_version.py --level patch --dry-run
    python3 scripts/bump_version.py --version 0.2.0
    python3 scripts/bump_version.py --sync               # производные к VERSION
    python3 scripts/bump_version.py --state              # решение о выпуске
    python3 scripts/bump_version.py --notes              # тело раздела CHANGELOG
    python3 scripts/bump_version.py --release-body       # полный текст релиза

Версия печатается в stdout, сообщения — в stderr: так workflow забирает
результат через подстановку команды, не разбирая лог.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION_FILE = "VERSION"
MANIFEST_FILE = pathlib.Path("custom_components") / "asustor_adm" / "manifest.json"
PYPROJECT_FILE = "pyproject.toml"
CHANGELOG_FILE = "CHANGELOG.md"

LEVELS: Final = ("patch", "minor", "major")

#: Тег релиза: версия SemVer с префиксом ``v``.
TAG_PREFIX: Final = "v"

#: SemVer без предрелизных суффиксов: интеграция выпускается только релизами.
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MANIFEST_VERSION_RE = re.compile(r'^(\s*"version":\s*")[^"]*(")', re.MULTILINE)
PYPROJECT_VERSION_RE = re.compile(r'^version = "[^"]*"', re.MULTILINE)
UNRELEASED_HEADING = "## [Unreleased]"
LINK_RE = re.compile(r"^\[([^\]]+)\]:\s*(\S+)$", re.MULTILINE)
COMPARE_RE = re.compile(r"^(?P<base>.+)/compare/.*$")

#: Conventional Commits: тип, необязательная область, разделитель и описание.
COMMIT_RE = re.compile(
    r"^(?P<kind>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<summary>\S.*)$"
)
#: Служебные коммиты выпуска не попадают в список изменений релиза.
RELEASE_COMMIT_RE = re.compile(r"^chore\(release\)")
#: Формат ``git log``: короткий хеш, NUL-разделитель, тема коммита.
GIT_LOG_FORMAT: Final = "%h%x00%s"
GIT_TIMEOUT_SECONDS: Final = 60

#: Раздел списка изменений для каждого типа коммита.
GROUP_TITLES: Final[dict[str, str]] = {
    "feat": "Добавлено",
    "fix": "Исправлено",
    "perf": "Изменено",
    "refactor": "Изменено",
    "docs": "Документация",
    "test": "Тесты",
    "ci": "Служебное",
    "build": "Служебное",
    "chore": "Служебное",
    "style": "Служебное",
    "revert": "Служебное",
}
#: Порядок разделов в тексте релиза: сначала то, что видит пользователь.
GROUP_ORDER: Final = (
    "Добавлено",
    "Изменено",
    "Исправлено",
    "Документация",
    "Тесты",
    "Служебное",
    "Прочее",
)
#: Раздел для коммитов без типа Conventional Commits.
OTHER_GROUP: Final = "Прочее"


class VersionError(Exception):
    """Нарушение формата версии или структуры файлов."""


@dataclass(frozen=True, slots=True)
class Commit:
    """Строка журнала git: короткий хеш и тема."""

    sha: str
    subject: str

    @property
    def group(self) -> str:
        """Раздел списка изменений по типу коммита."""
        match = COMMIT_RE.match(self.subject)
        if match is None:
            return OTHER_GROUP
        return GROUP_TITLES.get(match.group("kind"), OTHER_GROUP)


def parse_semver(text: str) -> tuple[int, int, int]:
    """Разобрать версию ``X.Y.Z``; иначе — ``VersionError``."""
    match = SEMVER_RE.match(text.strip())
    if match is None:
        raise VersionError(
            f"версия {text!r} не соответствует SemVer X.Y.Z (без префикса v)"
        )
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def parse_tag(text: str) -> tuple[int, int, int] | None:
    """Разобрать тег ``vX.Y.Z``; любой другой тег — ``None``."""
    value = text.strip()
    if not value.startswith(TAG_PREFIX):
        return None
    try:
        return parse_semver(value[len(TAG_PREFIX) :])
    except VersionError:
        return None


def released_tags(tags: Iterable[str]) -> list[tuple[tuple[int, int, int], str]]:
    """Теги-версии, отсортированные по возрастанию версии.

    Посторонние теги (например, имя ветки) не участвуют в решениях
    о выпуске и не ломают разбор.
    """
    parsed = [(parse_tag(name), name) for name in tags]
    known = [(key, name) for key, name in parsed if key is not None]
    return sorted(known)


def previous_tag(tags: Iterable[str], version: str) -> str | None:
    """Последний выпущенный тег, который строго меньше ``version``."""
    current = parse_semver(version)
    earlier = [name for key, name in released_tags(tags) if key < current]
    return earlier[-1] if earlier else None


def release_decision(version: str, tags: Iterable[str]) -> tuple[bool, str]:
    """Нужен ли выпуск версии: решение и его причина.

    Выпуск не повторяется для существующего тега и не выполняется при
    понижении версии — иначе workflow затирал бы уже опубликованные релизы.
    """
    names = {name.strip() for name in tags}
    current = parse_semver(version)
    tag = f"{TAG_PREFIX}{version}"
    if tag in names:
        return False, f"тег {tag} уже существует"
    released = released_tags(names)
    if released and released[-1][0] > current:
        raise VersionError(
            f"версия {version} меньше последнего выпуска {released[-1][1]}: "
            "понижение версии не выпускается"
        )
    if released:
        return True, f"версия {version} новее последнего выпуска {released[-1][1]}"
    return True, f"первый выпуск версии {version}"


def bump(current: str, level: str) -> str:
    """Поднять версию на один шаг: ``patch``, ``minor`` или ``major``."""
    if level not in LEVELS:
        raise VersionError(f"неизвестный уровень {level!r}, ожидается {LEVELS}")
    major, minor, patch = parse_semver(current)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def read_version(root: pathlib.Path = ROOT) -> str:
    """Прочитать версию из файла ``VERSION`` и проверить её формат."""
    path = root / VERSION_FILE
    if not path.exists():
        raise VersionError(f"нет файла {VERSION_FILE}: он источник истины версии")
    # Берём первую непустую строку: файл должен содержать ровно один номер.
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    values = [line for line in lines if line]
    if not values:
        raise VersionError(f"файл {VERSION_FILE} пуст")
    version = values[0]
    parse_semver(version)
    return version


def render_manifest(text: str, version: str) -> str:
    """Подставить версию в текст ``manifest.json``, не меняя форматирование."""
    if MANIFEST_VERSION_RE.search(text) is None:
        raise VersionError('в manifest.json нет строки "version"')
    updated = MANIFEST_VERSION_RE.sub(rf"\g<1>{version}\g<2>", text, count=1)
    # Манифест остаётся валидным JSON с ровно одной новой версией.
    json.loads(updated)
    return updated


def render_pyproject(text: str, version: str) -> str:
    """Подставить версию в текст ``pyproject.toml``."""
    if PYPROJECT_VERSION_RE.search(text) is None:
        raise VersionError("в pyproject.toml нет строки version")
    return PYPROJECT_VERSION_RE.sub(f'version = "{version}"', text, count=1)


def promote_changelog(text: str, version: str, date: str) -> str:
    """Превратить ``[Unreleased]`` в раздел выпускаемой версии.

    Вставка идёт сразу после заголовка ``[Unreleased]``, поэтому новый
    пустой раздел для будущих изменений не нужен: он остаётся на месте.
    """
    if f"## [{version}]" in text:
        raise VersionError(f"в CHANGELOG.md уже есть раздел {version}")
    if UNRELEASED_HEADING not in text:
        raise VersionError(f"в CHANGELOG.md нет заголовка {UNRELEASED_HEADING!r}")
    section = f"## [{version}] - {date}"
    updated = text.replace(
        f"{UNRELEASED_HEADING}\n", f"{UNRELEASED_HEADING}\n\n{section}\n", 1
    )
    return _rewrite_links(updated, version)


def compare_base(text: str) -> str | None:
    """Адрес репозитория из ссылки сравнения ``[Unreleased]`` в CHANGELOG."""
    for name, url in LINK_RE.findall(text):
        if name != "Unreleased":
            continue
        match = COMPARE_RE.match(url)
        return match.group("base") if match is not None else None
    return None


def _rewrite_links(text: str, version: str) -> str:
    """Обновить сравнение ``[Unreleased]`` и добавить ссылку на релиз."""
    base = compare_base(text)
    if not base:
        return text
    text = LINK_RE.sub(
        lambda m: (
            f"[Unreleased]: {base}/compare/v{version}...HEAD"
            if m.group(1) == "Unreleased"
            else m.group(0)
        ),
        text,
        count=1,
    )
    release_link = f"[{version}]: {base}/releases/tag/v{version}"
    if f"[{version}]:" in text:
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("[Unreleased]:"):
            lines.insert(index + 1, release_link)
            break
    else:
        lines.extend(["", release_link])
    return "\n".join(lines) + "\n"


def changelog_notes(text: str, version: str) -> str:
    """Вернуть тело раздела версии — оно же текст релиза."""
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*$", re.MULTILINE)
    match = heading.search(text)
    if match is None:
        raise VersionError(f"в CHANGELOG.md нет раздела {version}")
    rest = text[match.end() :]
    stop = re.search(r"^(## |\[[^\]]+\]:)", rest, re.MULTILINE)
    body = rest[: stop.start()] if stop is not None else rest
    notes = body.strip()
    if not notes:
        raise VersionError(f"раздел {version} в CHANGELOG.md пуст")
    return notes


def changelog_notes_or_none(text: str, version: str) -> str | None:
    """Тело раздела версии или ``None``: в авторежиме раздел необязателен."""
    try:
        return changelog_notes(text, version)
    except VersionError:
        return None


def render_commits(commits: Iterable[Commit]) -> str:
    """Markdown-список коммитов, сгруппированный по смыслу изменения."""
    groups: dict[str, list[Commit]] = {}
    for commit in commits:
        groups.setdefault(commit.group, []).append(commit)
    blocks: list[str] = []
    for title in GROUP_ORDER:
        items = groups.get(title)
        if not items:
            continue
        lines = [f"#### {title}", ""]
        lines.extend(f"- `{commit.sha}` {commit.subject}" for commit in items)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _git(root: pathlib.Path, *args: str) -> str:
    """Выполнить git в каталоге репозитория; ошибка — ``VersionError``."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VersionError(f"git {args[0]} недоступен: {error}") from error
    if result.returncode != 0:
        raise VersionError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def git_tags(root: pathlib.Path) -> list[str]:
    """Все теги репозитория."""
    return [line.strip() for line in _git(root, "tag", "--list").splitlines() if line]


def git_commits(root: pathlib.Path, revision_range: str) -> list[Commit]:
    """Коммиты диапазона без merge и без служебных коммитов выпуска."""
    output = _git(
        root, "log", "--no-merges", f"--format={GIT_LOG_FORMAT}", revision_range
    )
    commits: list[Commit] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x00")
        if RELEASE_COMMIT_RE.match(subject):
            continue
        commits.append(Commit(sha=sha.strip(), subject=subject.strip()))
    return commits


def release_body(root: pathlib.Path, version: str) -> str:
    """Собрать текст релиза: раздел CHANGELOG, коммиты и ссылка сравнения.

    Список изменений строится относительно предыдущего релиза, а не от
    начала истории: читателю нужна дельта с прошлой версии. Если прошлого
    тега нет, остаётся раздел CHANGELOG — описывать нечего.
    """
    parse_semver(version)
    changelog = (root / CHANGELOG_FILE).read_text(encoding="utf-8")
    notes = changelog_notes_or_none(changelog, version)
    tags = git_tags(root)
    previous = previous_tag(tags, version)
    commits = git_commits(root, f"{previous}..HEAD") if previous else []
    blocks: list[str] = []
    if notes:
        blocks.append(notes)
    rendered = render_commits(commits)
    if rendered:
        heading = f"### Коммиты {previous}...v{version}" if previous else "### Коммиты"
        blocks.append(f"{heading}\n\n{rendered}")
    base = compare_base(changelog)
    if base and previous:
        link = f"{base}/compare/{previous}...v{version}"
        blocks.append(f"**Полный список изменений**: {link}")
    body = "\n\n".join(blocks).strip()
    if not body:
        raise VersionError(
            f"для версии {version} нечего публиковать: раздел CHANGELOG пуст, "
            "коммитов с прошлого релиза нет"
        )
    return body


def release_state(root: pathlib.Path) -> dict[str, object]:
    """Состояние версии для workflow: нужен ли выпуск и что в него войдёт."""
    version = read_version(root)
    tags = git_tags(root)
    should_release, reason = release_decision(version, tags)
    return {
        "version": version,
        "tag": f"{TAG_PREFIX}{version}",
        "previous_tag": previous_tag(tags, version),
        "should_release": should_release,
        "reason": reason,
    }


def render_version_files(root: pathlib.Path, version: str) -> dict[pathlib.Path, str]:
    """Ожидаемое содержимое всех файлов версии для ``version``."""
    manifest_path = root / MANIFEST_FILE
    pyproject_path = root / PYPROJECT_FILE
    for path in (manifest_path, pyproject_path):
        if not path.exists():
            raise VersionError(f"нет файла {path}")
    return {
        root / VERSION_FILE: f"{version}\n",
        manifest_path: render_manifest(
            manifest_path.read_text(encoding="utf-8"), version
        ),
        pyproject_path: render_pyproject(
            pyproject_path.read_text(encoding="utf-8"), version
        ),
    }


def set_version(root: pathlib.Path, version: str) -> list[pathlib.Path]:
    """Записать версию в ``VERSION``, манифест и ``pyproject.toml``."""
    parse_semver(version)
    rendered = render_version_files(root, version)
    for path, text in rendered.items():
        path.write_text(text, encoding="utf-8")
    return list(rendered)


def sync_version(root: pathlib.Path) -> tuple[str, list[pathlib.Path]]:
    """Привести производные файлы к версии из ``VERSION``.

    Возвращает версию и только реально изменённые файлы: при полном
    совпадении workflow не создаёт пустой коммит.
    """
    version = read_version(root)
    changed: list[pathlib.Path] = []
    for path, text in render_version_files(root, version).items():
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        path.write_text(text, encoding="utf-8")
        changed.append(path)
    return version, changed


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Версия интеграции: источник истины — файл VERSION.",
    )
    parser.add_argument("--level", choices=LEVELS, help="шаг инкремента версии")
    parser.add_argument("--version", help="явная версия X.Y.Z")
    parser.add_argument(
        "--notes",
        nargs="?",
        const="",
        metavar="X.Y.Z",
        help="напечатать тело раздела CHANGELOG (по умолчанию для текущей версии)",
    )
    parser.add_argument(
        "--release-body",
        nargs="?",
        const="",
        metavar="X.Y.Z",
        help="напечатать полный текст релиза (CHANGELOG, коммиты, ссылка)",
    )
    parser.add_argument(
        "--state",
        action="store_true",
        help="напечатать JSON с решением о выпуске",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="привести manifest.json и pyproject.toml к версии из VERSION",
    )
    parser.add_argument("--dry-run", action="store_true", help="ничего не менять")
    parser.add_argument("--today", help="дата выпуска YYYY-MM-DD (для проверок)")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=ROOT,
        help="корень репозитория (по умолчанию — каталог скрипта)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, root: pathlib.Path | None = None) -> int:
    """Точка входа CLI: версия в stdout, сообщения в stderr."""
    args = _parse_args(argv)
    base = pathlib.Path(root or args.root)
    changelog_path = base / CHANGELOG_FILE
    try:
        current = read_version(base)
        if args.state:
            print(json.dumps(release_state(base), ensure_ascii=False, indent=2))
            return 0
        if args.release_body is not None:
            print(release_body(base, args.release_body or current))
            return 0
        if args.sync:
            version, changed = sync_version(base)
            print(version)
            if changed:
                names = ", ".join(str(path.relative_to(base)) for path in changed)
                print(f"синхронизированы файлы: {names}", file=sys.stderr)
            else:
                print("производные файлы уже совпадают с VERSION", file=sys.stderr)
            return 0
        if args.notes is not None:
            version = args.notes or current
            text = changelog_path.read_text(encoding="utf-8")
            print(changelog_notes(text, version))
            return 0

        if args.version:
            target = args.version
            parse_semver(target)
        elif args.level:
            target = bump(current, args.level)
        else:
            print(current)
            return 0

        if target == current:
            print(target)
            print(f"версия не меняется: {current}", file=sys.stderr)
            return 0

        date = args.today or datetime.date.today().isoformat()
        text = changelog_path.read_text(encoding="utf-8")
        changelog = promote_changelog(text, target, date)
        if args.dry_run:
            print(target)
            print(
                f"будет выпущена версия {target} от {date}; "
                f"правятся {VERSION_FILE}, {MANIFEST_FILE}, {PYPROJECT_FILE}, "
                f"{CHANGELOG_FILE}",
                file=sys.stderr,
            )
            return 0
        paths = set_version(base, target)
        changelog_path.write_text(changelog, encoding="utf-8")
        print(target)
        changed = ", ".join(str(path.relative_to(base)) for path in paths)
        message = f"версия {current} -> {target}; обновлены {changed}, {CHANGELOG_FILE}"
        print(message, file=sys.stderr)
        return 0
    except VersionError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
