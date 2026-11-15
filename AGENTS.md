# AGENTS.md

## Проект

Кастомная интеграция Home Assistant для NAS ASUSTOR под управлением ADM: домен `asustor_adm`, репозиторий `ha-asustor-adm` (HACS custom repository). Данные берутся из внутреннего HTTP API ADM на порту 8001 — без SNMP и без облака ASUSTOR.

Публичной документации на этот API не существует: контракт восстановлен по захватам реальных запросов и зафиксирован в `openspec/specs/`. Любое поле ответа может измениться в следующей прошивке, поэтому разбор обязан оставаться устойчивым. Проверено на AS3304T (ADM 5.1.4.RM62), целевая версия Home Assistant — 2025.1+.

Пользовательское описание — [README.md](README.md); обоснование решений D1–D13 — [design.md](openspec/changes/archive/2026-11-15-add-asustor-adm-integration/design.md).

## Карта репозитория

- `custom_components/asustor_adm/` — интеграция:
  - `api.py` — клиент ADM: form-urlencoded POST, `sid` в query, разбор конверта, одна повторная авторизация по коду `5000`;
  - `const.py` — домен, эндпоинты (`Endpoint`), коды ошибок, интервалы, определения сервисов;
  - `parse.py` — разбор ответов в модели, устойчивый к отсутствующим и лишним полям;
  - `values.py` — приведение значений: `strip()`, кБ → МиБ, байты → ГиБ, доли в процентах;
  - `models.py` — неизменяемые датаклассы `SysInfo`, `Activity`, `Volume`, `Disk`, `FastData`, `SlowData` и др.;
  - `coordinator.py` — быстрый и медленный циклы, частичная деградация, сохранение последнего состояния прошивки;
  - `entity.py` — `ADMRuntime`, базовые сущности циклов, `DynamicEntityManager`;
  - `sensor.py`, `binary_sensor.py`, `button.py`, `update.py` — платформы;
  - `config_flow.py` — настройка, переавторизация, интервалы опроса;
  - `diagnostics.py` — выгрузка с маскированием секретов;
  - `strings.json`, `translations/en.json`, `translations/ru.json` — строки интерфейса;
  - `manifest.json`, `brand/` — манифест и иконки.
- `tests/unit/` — быстрый набор без Home Assistant (106 тестов);
- `tests/` — полный набор с Home Assistant (200 тестов);
- `tests/fixtures/` — санитизированные ответы ADM, правила пополнения — [README.md](tests/fixtures/README.md);
- `openspec/` — спецификации `specs/`, активные изменения `changes/`, архив `changes/archive/`;
- `.github/workflows/ci.yml` — проверки на пуш и pull request;
- `.github/workflows/release.yml` — выпуск версии, тег и релиз по ручному запуску;
- `VERSION` — единственный источник номера версии; `CHANGELOG.md` — история по Keep a Changelog;
- `scripts/bump_version.py` — bump версии, синхронизация `manifest.json` и `pyproject.toml`, раздел CHANGELOG и текст релиза;
- `pyproject.toml` — настройки ruff, `pytest.ini`, `requirements_test.txt`, `hacs.json`;
- `.dsh/` — инструменты агента в рабочем каталоге, в `.gitignore`, править их не нужно.

## Команды

```bash
python3 -m pytest tests/unit -q --confcutdir=tests/unit   # быстрый набор, 106 тестов, без Home Assistant
python3 -m pytest -q                                      # полный набор, 200 тестов, нужен Home Assistant
python3 -m ruff check .                                   # линт
python3 -m ruff format --check .                          # проверка формата (переформат: без --check)
python3 scripts/bump_version.py --level patch --dry-run   # что изменится при выпуске patch
python3 scripts/bump_version.py --notes                   # тело релиза текущей версии
openspec validate --all --strict                          # валидация спек и изменений
```

`pytest.ini` задаёт `asyncio_mode = auto`, `testpaths = tests`, `pythonpath = . tests`; `pytest.ini` уже включает `-q`. Для быстрого набора нужны `pytest`, `pytest-asyncio`, `pytest-aiohttp`, `aiohttp`; для полного — `pip install -r requirements_test.txt`.

CI — один файл `.github/workflows/ci.yml` на два хостинга: и GitHub Actions, и Forgejo Actions ищут workflow в `.github/workflows`. Метка раннера берётся из переменной репозитория `CI_RUNNER` (`runs-on: ${{ vars.CI_RUNNER || 'ubuntu-latest' }}`): на Forgejo она задана как `main` (self-hosted act_runner), на GitHub не задана и подставляется `ubuntu-latest` (публичный репозиторий, минуты не тарифицируются). На каждый пуш и pull request — `ruff check`, `ruff format --check` и быстрый набор; полный набор запускается вручную (`Run workflow` → `full_suite`). Метка, для которой нет онлайн-раннера, оставляет job в очереди навсегда — это и была причина «pipeline ждёт раннера» на GitHub.

Версия — `VERSION` в корне (единственный источник), `manifest.json` и `pyproject.toml` производны: менять номер в них руками нельзя, только `python3 scripts/bump_version.py --level <patch|minor|major>` или `--version X.Y.Z`. Равенство трёх значений проверяет `tests/unit/test_version.py`, поэтому расхождение ломает CI, а не установку у пользователя. Выпуск — `.github/workflows/release.yml` (ручной запуск): bump файлов, коммит `chore(release): vX.Y.Z`, тег и релиз через API того хостинга, где запущен workflow; тег и релиз идемпотентны, повторный запуск добавит только недостающее. Перед выпуском изменения описываются в разделе `## [Unreleased]` файла `CHANGELOG.md` — при выпуске он становится разделом версии и текстом релиза, пустой раздел выпустить нельзя.

## Проверки перед завершением задачи

```bash
python3 -m ruff check . && python3 -m ruff format --check .
python3 -m pytest tests/unit -q --confcutdir=tests/unit
python3 -m pytest -q
openspec validate --all --strict    # если менялись спеки
```

Прогон против живого NAS не выполняется: тесты работают только на фикстурах и подменённом клиенте.

## Архитектура и поток данных

`ADMClient` (одна сессия, общий для записи) → `ADMFastCoordinator` / `ADMSlowCoordinator` → `ADMRuntime` → сущности платформ. Ошибки клиента переходят в `ConfigEntryAuthFailed` (переавторизация) или в `UpdateFailed` (недоступность), а не в исключения сущностей.

- **Быстрый цикл** (по умолчанию 60 с, 4 запроса): `act.cgi?act=list`, `sysinfo.cgi?act=sys`, `volume.cgi?act=list`, `disk_smart.cgi?act=list`.
- **Медленный цикл** (по умолчанию 300 с): 8 эндпоинтов сервисов, `sysinfo.cgi?act=net|wan`, `onlineuser.cgi`, `extdisk.cgi`, `taskmonitor.cgi`, `firmwarestatus.cgi`, `appcentral.cgi` и по одному `volume.cgi?act=get&vid=N` на том.
- **По требованию**, вне циклов: `disk_smart.cgi?act=smart&did=N` для сущности SMART, отключённой по умолчанию и обновляемой через `homeassistant.update_entity`.

Новый эндпоинт в цикле опроса — это рост числа CGI-процессов на NAS: добавлять его только с обоснованием, обновлять спеку, `design.md` и тест состава цикла.

## Инварианты (нарушать нельзя)

1. **Успех — только явный `success: true`.** Ответ без `success`, но с `error_code` — неуспех; ответ без обоих полей — полезные данные. Код `5000` — единственный, приводящий к повторной авторизации; ровно одна повторная попытка, остальные коды не ретраятся.
2. **Секреты не попадают никуда, кроме памяти.** Пароль, `sid`, `passport`, учётная запись, серийный номер и адреса маскируются в `diagnostics.py`; в журнал пишется только путь эндпоинта, никогда — query string и тело запроса.
3. **Разбор не бросает исключений.** Отсутствующее поле даёт `None` и недоступность одной сущности, лишние поля игнорируются. Единственная широкая обработка — `_safe_parse` в координаторе, это осознанная граница устойчивости.
4. **Неизвестное не публикуется как ноль или `false`.** `available` сущности повторяет наличие данных; отсутствующий сервис, диск или том не превращается в выключенный.
5. **Идентификаторы сущностей стабильны.** `unique_id = f"{identifier}_{suffix}"`, где `identifier` — серийный номер NAS (иначе адрес хоста); для дисков ключ строится по номеру отсека, для томов — по `vid`, для сервисов — по имени сервиса. Существующие суффиксы не переименовываются: это ломает записи реестра у пользователей.
6. **Гейтирование по фактическим возможностям.** Кнопки питания — только при `isadministrators`; кнопка сна — при `cansuspend`; кулеры — по длине `fan_speed`; внешние диски — по наличию `disks[]`; сущность обновления ADM — только при известной целевой версии.
7. **Питание — только по явному действию пользователя.** После `shutdown`/`restart`/`suspend` координаторы помечаются недоступными, повторных отправок и опросов «в догонку» нет; восстановление происходит при первом успешном ответе.
8. **Каждой сущности — ключ перевода.** Новая сущность без записи в `strings.json` и обоих переводах не считается готовой; `translations/en.json` обязан совпадать с `strings.json`.
9. **Никаких новых зависимостей.** Достаточно `aiohttp` из окружения Home Assistant; сторонние PyPI-пакеты не добавляются.

## Тесты

- Полный набор монтирует `FakeADMClient` в `custom_components.asustor_adm.ADMClient` и `custom_components.asustor_adm.config_flow.ADMClient`. Если новый модуль создаёт клиент, он должен импортировать `ADMClient` на уровне модуля и получать подмену — иначе понадобится третья точка `monkeypatch`.
- Быстрый набор (`tests/unit`) импортирует только подмодули через облегчённый пакет из `tests/unit/conftest.py`: `__init__.py` интеграции не выполняется. Поэтому в `tests/unit` нельзя импортировать сам пакет и модули Home Assistant.
- Каждая фикстура должна использоваться хотя бы одним тестом — это проверяет `tests/unit/test_fixture_coverage.py`. Новая фикстура без теста ломает сбор.
- Фикстуры — санитизированные ответы: без серийных номеров, `sid`, паспорта учётной записи, адресов и query string. Синтетические фикстуры помечаются в [README.md](tests/fixtures/README.md).
- Тест проверяет наблюдаемое поведение (состояния и атрибуты сущностей, число запросов, недоступность), а не внутренние вызовы. Докстринги тестов — по-русски.

## Спеки и порядок реализации

Проект ведётся по OpenSpec (`schema: spec-driven`), источник истины по поведению — `openspec/specs/` (шесть способностей: `system-metrics`, `storage-health`, `services-status`, `firmware-updates`, `power-control`, `external-devices`).

1. Изменение начинается с `openspec/changes/<ГГГГ-ММ-ДД>-<имя>/`: `proposal.md` (зачем, что меняется, чего не делаем), `design.md` (только развилки и их основания), дельта-спеки, `tasks.md` с проверяемыми задачами.
2. Реализация идёт по `tasks.md`; `[x]` ставится только после зелёных проверок и обновления README, если поведение видно пользователю.
3. Завершённое изменение архивируется: `openspec archive <имя>` переносит его в `changes/archive/` и обновляет `openspec/specs/`. Архивированные изменения и основные спеки вручную не правятся.
4. Язык артефактов — русский, структурные заголовки и ключевые слова `SHALL`/`MUST` — английские (задано в `openspec/config.yaml`).
5. Поведение описывается один раз: спека — договор и сценарии, README — что видит пользователь, `design.md` — почему выбрано так.

## Соглашения кода

- Python 3.12+, `from __future__ import annotations`, полные аннотации, `Final` для констант, `frozen=True, slots=True` для датаклассов, `kw_only=True` для описаний сущностей.
- Стиль — ruff: `line-length = 88`, наборы `E, F, W, I, UP, B, SIM, C4, RUF`; формат проверяется `ruff format --check`, поэтому форматировать надо им же.
- Докстринги и комментарии — по-русски, короткие; комментарий объясняет инвариант или неочевидное решение, а не повторяет код.
- Логирование: `debug` для штатной деградации (недоступный эндпоинт, неудачная проверка обновлений), `warning` только для неожиданной структуры ответа; без параметров запроса и секретов.
- Ошибки — типизированные из `exceptions.py`; наружу из платформ отдаётся `HomeAssistantError` с ключом перевода.
- README синхронизируется с кодом: состав сущностей, интервалы по умолчанию, число тестов в разделе «Тесты».

## Коммиты

- Тема — Conventional Commits на английском (`ci:`, `test:`, `docs:`, `feat:`, `fix:`), тело — английский, по существу изменения и его проверки.
- Коммит делается по достижении целостного состояния: работающая проверка, обновлённые спеки и README. Промежуточные состояния не коммитятся.
- В индекс не попадают `.dsh/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.venv/` — они в `.gitignore`; перед коммитом проверяется `git status`.
