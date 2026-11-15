"""Полнота использования фикстур (задача 9.2)."""

from __future__ import annotations

import pathlib

from helpers import FIXTURES_DIR

TESTS_DIR = pathlib.Path(__file__).parent


def test_every_fixture_is_used_by_a_test() -> None:
    """Каждая фикстура спайка используется хотя бы одним тестом."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if path.name != "test_fixture_coverage.py"
    )
    fixtures = sorted(path.stem for path in FIXTURES_DIR.glob("*.json"))
    assert fixtures
    unused = [name for name in fixtures if name not in sources]
    assert unused == [], f"фикстуры без теста: {unused}"
