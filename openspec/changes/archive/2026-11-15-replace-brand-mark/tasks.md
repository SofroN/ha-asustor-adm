# Tasks

## 1. Ассеты

- [x] 1.1 Скачать `https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/asustor.svg` и зафиксировать состав: `viewBox="0 0 1024 1024"`, `<circle r="512" fill="#0052a4">`, один `<path fill="#fff">`; проверка: `grep -o '<[a-z]*' asustor.svg` даёт ровно `circle` и `path`, круга другого цвета нет.
- [x] 1.2 Отрендерить `brand/icon.png` 256×256 и `brand/icon@2x.png` 512×512 из этого SVG через `cairosvg`, установленный во временный каталог; проверка: `python3 -m pytest tests/unit/test_brand.py -q --confcutdir=tests/unit` — размеры, прозрачные углы и центровка зелёные.
- [x] 1.3 Собрать `brand/logo.png` 300×55, `brand/logo@2x.png` 600×110 (чёрный wordmark) и `brand/dark_logo.png`, `brand/dark_logo@2x.png` (белый) из того же `<path>`; удалить `brand/dark_icon.png` и `brand/dark_icon@2x.png`; проверка: тест размеров и контраста в `tests/unit/test_brand.py` зелёный, в каталоге ровно шесть PNG.
- [x] 1.4 Обновить `tests/unit/test_brand.py` под знак: прозрачные углы, 60–90 % непрозрачных пикселей, больше 85 % заливки `#0052a4`, 2–10 % белых букв, контраст — только для логотипов; проверка: `python3 -m ruff check tests/unit/test_brand.py`, `python3 -m ruff format --check tests/unit/test_brand.py`, пять тестов файла зелёные.

## 2. Документация

- [x] 2.1 Добавить в `CHANGELOG.md` запись `### Изменено` в `## [Unreleased]` о новом знаке и удалении тёмной иконки; проверка: запись есть в разделе Unreleased и упоминает `dashboard-icons`.
- [x] 2.2 Указать в `README.md` происхождение знака (каталог `dashboard-icons`, товарный знак принадлежит ASUSTOR); проверка: строка присутствует и не расходится с `design.md` D1.

## 3. Проверки

- [x] 3.1 Прогнать `python3 -m ruff check .`, `python3 -m ruff format --check .`, `python3 -m pytest tests/unit -q --confcutdir=tests/unit`, `python3 -m pytest -q`, `openspec validate --all --strict`; проверка: все команды завершаются успешно.
- [x] 3.2 Сверить число тестов в README с фактическим выводом `python3 -m pytest -q`; проверка: значения совпадают.

## Workflow follow-up

- Архивировать изменение командой `openspec archive 2026-11-15-replace-brand-mark` после приёмки.
