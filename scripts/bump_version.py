"""Единое управление версией интеграции.

Источник истины — файл ``VERSION`` в корне репозитория. ``manifest.json``
(его читает HACS) и ``pyproject.toml`` — производные: их обновляет этот
скрипт, а согласованность проверяет ``tests/unit/test_version.py``.

Режимы:

    python3 scripts/bump_version.py                      # текущая версия
    python3 scripts/bump_version.py --level patch --dry-run
    python3 scripts/bump_version.py --version 0.2.0
    python3 scripts/bump_version.py --notes              # тело релиза

Версия печатается в stdout, сообщения — в stderr: так workflow забирает
результат через подстановку команды, не разбирая лог.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION_FILE = "VERSION"
MANIFEST_FILE = pathlib.Path("custom_components") / "asustor_adm" / "manifest.json"
PYPROJECT_FILE = "pyproject.toml"
CHANGELOG_FILE = "CHANGELOG.md"

LEVELS = ("patch", "minor", "major")

#: SemVer без предрелизных суффиксов: интеграция выпускается только релизами.
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MANIFEST_VERSION_RE = re.compile(r'^(\s*"version":\s*")[^"]*(")', re.MULTILINE)
PYPROJECT_VERSION_RE = re.compile(r'^version = "[^"]*"', re.MULTILINE)
UNRELEASED_HEADING = "## [Unreleased]"
LINK_RE = re.compile(r"^\[([^\]]+)\]:\s*(\S+)$", re.MULTILINE)
COMPARE_RE = re.compile(r"^(?P<base>.+)/compare/.*$")


class VersionError(Exception):
    """Нарушение формата версии или структуры файлов."""


def parse_semver(text: str) -> tuple[int, int, int]:
    """Разобрать версию ``X.Y.Z``; иначе — ``VersionError``."""
    match = SEMVER_RE.match(text.strip())
    if match is None:
        raise VersionError(
            f"версия {text!r} не соответствует SemVer X.Y.Z (без префикса v)"
        )
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


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


def _rewrite_links(text: str, version: str) -> str:
    """Обновить сравнение ``[Unreleased]`` и добавить ссылку на релиз."""
    base = ""
    for name, url in LINK_RE.findall(text):
        if name != "Unreleased":
            continue
        match = COMPARE_RE.match(url)
        if match is not None:
            base = match.group("base")
        break
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


def set_version(root: pathlib.Path, version: str) -> list[pathlib.Path]:
    """Записать версию в ``VERSION``, манифест и ``pyproject.toml``."""
    parse_semver(version)
    manifest_path = root / MANIFEST_FILE
    pyproject_path = root / PYPROJECT_FILE
    for path in (manifest_path, pyproject_path):
        if not path.exists():
            raise VersionError(f"нет файла {path}")
    manifest = render_manifest(manifest_path.read_text(encoding="utf-8"), version)
    pyproject = render_pyproject(pyproject_path.read_text(encoding="utf-8"), version)
    (root / VERSION_FILE).write_text(f"{version}\n", encoding="utf-8")
    manifest_path.write_text(manifest, encoding="utf-8")
    pyproject_path.write_text(pyproject, encoding="utf-8")
    return [root / VERSION_FILE, manifest_path, pyproject_path]


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
        help="напечатать тело релиза (по умолчанию для текущей версии)",
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
