# Tasks

## 1. Сравнение версий

- [x] 1.1 Добавить в `values.py` функцию сравнения версий ADM по правилам `design.md` D2: сегменты по точкам, цифровые как числа, прочие как строки без учёта регистра, префикс считается равным, пустое или несравнимое значение даёт отдельный результат; проверка: `python3 -m pytest tests/unit/test_values.py -q` с новыми случаями — `5.1.5.RN11` новее `5.1.4.RM62`, `5.1.4.RM62` равно самой себе, `5.1.3.RN1` старее, `RM62` старее `RN11`, `10.0` новее `9.9`, `5.1.4` не новее `5.1.4.RM62`, пустая строка и `None` дают «не сравнимо».

## 2. Модель, разбор и координатор

- [x] 2.1 В `models.py` расширить `FirmwareInfo` полями `notification_flag` и `last_check_time`; в `parse.py` переписать `parse_firmware`: возвращать только данные ответа, `update_available` всегда `None` (признак вычисляется после сведения), целевая версия по-прежнему из `new_version` / `latest_version` / `available_version`; проверка: `python3 -m pytest tests/unit/test_parse.py -q` — на `firmware.json` установленная версия `5.1.4.RM62`, `update_available is None`, `notification_flag is True`, `last_check_time == "2026/10/26"`; на `firmware_up_to_date.json` — `update_available is None`, `notification_flag is False`; на `firmware_with_target.json` — целевая версия `5.1.5.RN11`.
- [x] 2.2 В `coordinator.py` разделить сведение и вычисление по `design.md` D3: установленная версия наследуется из предыдущего состояния при отсутствии в ответе, целевая версия, флаг и время не наследуются, признак вычисляется из сведённых версий; при флаге без подтверждённой версии писать строку `debug` с версиями и флагом (без параметров запроса и секретов); `_carry_firmware` сохраняет поведение «последнее подтверждённое значение плюс код ошибки»; проверка: `python3 -m pytest tests/test_firmware.py -q` — успешный ответ без целевой версии делает сенсор недоступным, неудачная проверка сохраняет последнее подтверждённое значение и код ошибки в атрибуте `last_check_error`, смежные сущности остаются доступными.

## 3. Сущности

- [x] 3.1 В `binary_sensor.py` перевести `ADMUpdateAvailableSensor` на вычисленный признак: `is_on` из `FirmwareInfo.update_available`, `available` ложно при `None`, добавить атрибуты `notification_flag` и `last_check_time`; проверка: `python3 -m pytest tests/test_firmware.py -q` — на `firmware.json` состояние `unavailable` (ложного `on` нет), на `firmware_with_target.json` состояние `on` с атрибутами `target_version == "5.1.5.RN11"`, `notification_flag is True`, `last_check_time == "2026/11/14"`; при целевой версии, равной установленной или старше (маршрут задаётся словарём в тесте), состояние `off`.
- [x] 3.2 В `update.py` по `design.md` D4 создавать сущность только при подтверждённой более новой целевой версии, а `latest_version` отдавать так, чтобы Home Assistant не показывал обновление по равной, старшей или несравнимой версии; проверка: `python3 -m pytest tests/test_firmware.py -q` — с `firmware.json` сущности нет, с `firmware_with_target.json` состояние `on` и `latest_version == "5.1.5.RN11"`, после смены ответа на целевую версию, равную установленной, состояние `off` и `latest_version == "5.1.4.RM62"`.
- [x] 3.3 Добавить в `tests/test_firmware.py` сценарии из п. 3.1–3.2 вместо прежнего ожидания `on` на `firmware.json`, включая проверку отказа от установки (`test_install_is_refused`) на подтверждённой целевой версии; проверка: `python3 -m pytest tests/test_firmware.py -q` и `python3 -m pytest tests/test_icons.py -q` зелёные, число запросов в сценарии отказа не меняется.

## 4. Диагностика

- [x] 4.1 Добавить в раздел `firmware` выгрузки `diagnostics.py` поля `notification_flag` и `last_check_time` рядом с существующими; проверка: `python3 -m pytest tests/test_diagnostics.py -q` — на `firmware.json` в выгрузке `installed_version == "5.1.4.RM62"`, `update_available is None`, `notification_flag is True`, `last_check_time == "2026/10/26"`, маскирование секретов не изменилось.

## 5. Документация

- [x] 5.1 Обновить `README.md`: признак обновления ADM показывается только при подтверждённой более новой версии, атрибуты `notification_flag` и `last_check_time`, ограничение ADM 5.1.4 (сенсор остаётся «недоступно», потому что NAS не сообщает целевую версию и хранит только флаг уведомления), число тестов в разделе «Тесты» соответствует фактическому; проверка: разделы о сущностях, интервалах и тестах содержат перечисленные формулировки, а число тестов совпадает с выводом `python3 -m pytest -q`.
- [x] 5.2 Добавить в `CHANGELOG.md` раздел `## [Unreleased]` запись `### Исправлено` о ложном «обновление доступно» и новом источнике истины; проверка: `grep -n "Исправлено" -A3 CHANGELOG.md` показывает запись с упоминанием сверки версий.

## 6. Интеграционная проверка

- [x] 6.1 Прогнать обязательные проверки проекта: `python3 -m ruff check .`, `python3 -m ruff format --check .`, `python3 -m pytest tests/unit -q --confcutdir=tests/unit`, `python3 -m pytest -q`, `openspec validate --all --strict`; проверка: все команды завершаются успешно, быстрый и полный наборы не содержат падений, покрытие фикстур (`tests/unit/test_fixture_coverage.py`) остаётся зелёным без новых файлов фикстур.
- [x] 6.2 Перечитать `specs/firmware-updates/spec.md` и `design.md` и сверить с реализацией: каждое изменённое требование имеет наблюдаемую проверку в тестах, а расхождений между спекой и поведением сущностей нет; проверка: перечисление сценариев спеки с указанием теста, который их закрывает.

## Workflow follow-up

- Архивировать изменение командой `openspec archive fix-firmware-update-signal` после приёмки, чтобы дельта `firmware-updates` попала в основную спеку.
- После выпуска проверить на живом NAS (ADM 5.1.4.RM62): сенсор обновления не должен показывать `on` при «Используется последняя версия ПО», а атрибуты `notification_flag` и `last_check_time` должны быть видны; приложить свежий санитизированный захват `settings/firmwarestatus.cgi?act=get_static_info`, чтобы закрыть открытый вопрос `design.md` о смысле поля `update_available_notification`.
