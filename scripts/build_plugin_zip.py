"""Сборка архива плагина для установки в Home Assistant.

Архив повторяет структуру каталога конфигурации Home Assistant: внутри лежит
``custom_components/asustor_adm/...``, поэтому распаковка выполняется в корень
конфигурации:

    unzip asustor_adm-0.2.0.zip -d /config

Содержимое детерминировано — фиксированные отметки времени, порядок файлов
и права, — поэтому одинаковый исходник даёт побайтово одинаковый архив:
сравнение артефактов между запусками остаётся осмысленным.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import zipfile
from typing import Final

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT: Final = pathlib.Path("custom_components") / "asustor_adm"
VERSION_FILE = "VERSION"
DIST_DIR: Final = pathlib.Path("dist")

#: Мусор среды исполнения: в архив попадает только исходное содержимое.
EXCLUDED_DIRS: Final = frozenset({"__pycache__"})
EXCLUDED_SUFFIXES: Final = frozenset({".pyc", ".pyo"})
EXCLUDED_NAMES: Final = frozenset({".DS_Store", "Thumbs.db"})

#: Минимально допустимая дата в ZIP: значение делает архив воспроизводимым.
ARCHIVE_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)
FILE_MODE: Final = 0o644
UNIX_CREATE_SYSTEM: Final = 3


class ArchiveError(Exception):
    """Нарушение состава каталога плагина или версии."""


def read_version(root: pathlib.Path) -> str:
    """Прочитать версию из файла ``VERSION`` (первая непустая строка)."""
    path = root / VERSION_FILE
    if not path.exists():
        raise ArchiveError(f"нет файла {VERSION_FILE}")
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    versions = [line for line in values if line]
    if not versions:
        raise ArchiveError(f"файл {VERSION_FILE} пуст")
    return versions[0]


def manifest_version(root: pathlib.Path) -> str:
    """Версия из ``manifest.json``: её читает Home Assistant и HACS."""
    path = root / COMPONENT / "manifest.json"
    if not path.is_file():
        raise ArchiveError(f"нет файла {path.relative_to(root)}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ArchiveError(f"manifest.json не разбирается: {error}") from error
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise ArchiveError("в manifest.json нет строки version")
    return version


def collect_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Файлы плагина относительно его каталога, по алфавиту."""
    component = root / COMPONENT
    if not (component / "manifest.json").is_file():
        raise ArchiveError(f"нет каталога плагина {COMPONENT}")
    files: list[pathlib.Path] = []
    for path in sorted(component.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(component)
        if EXCLUDED_DIRS.intersection(relative.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES or path.name in EXCLUDED_NAMES:
            continue
        files.append(relative)
    return files


def build_archive(
    root: pathlib.Path, out: pathlib.Path, version: str | None = None
) -> pathlib.Path:
    """Собрать архив плагина в ``out`` и вернуть его путь.

    Версия из ``VERSION`` сверяется с манифестом: архив с чужой версией
    внутри сломал бы установку, поэтому рассинхрон — ошибка, а не догадка.
    """
    root = pathlib.Path(root)
    declared = manifest_version(root)
    target = version or read_version(root)
    if declared != target:
        raise ArchiveError(
            f"версия манифеста {declared} не совпадает с {VERSION_FILE} {target}: "
            "сначала синхронизируйте файлы версии"
        )
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in collect_files(root):
            info = zipfile.ZipInfo(
                (COMPONENT / relative).as_posix(), date_time=ARCHIVE_TIMESTAMP
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = UNIX_CREATE_SYSTEM
            info.external_attr = FILE_MODE << 16
            archive.writestr(info, (root / COMPONENT / relative).read_bytes())
    return out


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Архив плагина для распаковки в Home Assistant.",
    )
    parser.add_argument("--version", help="версия архива (по умолчанию из VERSION)")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        help="путь архива (по умолчанию dist/asustor_adm-<версия>.zip)",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=ROOT,
        help="корень репозитория (по умолчанию — каталог скрипта)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, root: pathlib.Path | None = None) -> int:
    """Точка входа CLI: путь архива в stdout, сообщение — в stderr."""
    args = _parse_args(argv)
    base = pathlib.Path(root or args.root)
    try:
        version = args.version or read_version(base)
        out = args.out or base / DIST_DIR / f"asustor_adm-{version}.zip"
        path = build_archive(base, out, version)
        with zipfile.ZipFile(path) as archive:
            count = len(archive.namelist())
    except (ArchiveError, OSError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2
    print(path)
    print(
        f"архив {path.name}: {count} файлов, {path.stat().st_size} байт",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
