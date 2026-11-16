# Tasks

## 1. Иконки сенсоров

- [x] 1.1 Добавить `mdi:memory` сенсору утилизации памяти (`memory_used_percent` в `FAST_SENSORS`, `sensor.py`): у процентов нет `device_class`, поэтому без явной иконки фронтенд рисует общий символ; проверка: `entity.icon == "mdi:memory"` в `tests/test_icons.py`.
- [x] 1.2 Добавить иконки направления сетевому обмену в `_build_dynamic_sensors`: приём — `mdi:download-network`, передача — `mdi:upload-network`; проверка: иконки `network_lan1_receive` и `network_lan1_transmit` различаются и совпадают с ожидаемыми.
- [x] 1.3 Добавить иконки направления дисковым скоростям: чтение — `mdi:download`, запись — `mdi:upload`; проверка: иконки `disk_1_read` и `disk_1_write` различаются и совпадают с ожидаемыми.
- [x] 1.4 Добавить `mdi:chart-donut` утилизации тома (`_build_volume_sensor`) и занятости внешнего диска (`_build_external_sensors`); ёмкость и свободное место остаются на иконке `device_class` `data_size`; проверка: иконки `volume_1_utilization` и `external_disk_usb2_used` заданы, `volume_1_capacity` и `external_disk_usb2_capacity` — нет.

## 2. Иконки кнопок

- [x] 2.1 Добавить отображение действий питания на иконки в `button.py`: `shutdown` → `mdi:power`, `restart` → `mdi:restart`, `suspend` → `mdi:power-sleep`; проверка: три теста-утверждения в `test_power_buttons_have_icons`.

## 3. Тесты

- [x] 3.1 Создать `tests/test_icons.py` с четырьмя тестами по `design.md` D2 и D5: проценты, направления (сеть и диск), кнопки, отсутствие явных иконок у сущностей с точным `device_class`; иконка читается через `hass.data["entity_components"][domain].get_entity(entity_id).icon`, потому что в атрибуты состояния она не попадает; проверка: `python3 -m pytest tests/test_icons.py -q` зелёный.
- [x] 3.2 Убедиться, что новые тесты падают на прежнем коде: временно откатить правки `sensor.py`/`button.py` (`git stash`) и прогнать `python3 -m pytest tests/test_icons.py -q` — ожидаются падения по каждому из трёх первых тестов; проверка: после возврата правок набор снова зелёный.

## 4. Документация

- [x] 4.1 Добавить запись в `## [Unreleased]` файла `CHANGELOG.md` о явных иконках сущностей.
- [x] 4.2 Обновить фактическое число тестов полного набора в `README.md` (разделы «Тесты» и упоминание сценариев).
- [x] 4.3 Дополнить `AGENTS.md`: конвенция выбора иконок в разделе «Соглашения кода» и фактическое число тестов полного набора; проверка: числа совпадают с выводом `python3 -m pytest -q`.
- [x] 4.4 Развязать `tests/unit/test_version.py::test_changelog_notes_rejects_empty_section` с содержимым рабочего `CHANGELOG.md`: тест задаёт пустой раздел `[Unreleased]` сам, потому что теперь раздел заполнен записью о выпуске; проверка: `python3 -m pytest tests/unit/test_version.py -q` зелёный.

## 5. Проверки и завершение

- [x] 5.1 Прогнать обязательные проверки: `python3 -m ruff check .`, `python3 -m ruff format --check .`, `python3 -m pytest tests/unit -q --confcutdir=tests/unit`, `python3 -m pytest -q`, `openspec validate --all --strict`.
- [ ] 5.2 Архивировать изменение: `openspec archive 2026-11-15-add-entity-icons`.
