# Tasks

## 1. Классификация недостатка прав

- [x] 1.1 Добавить `ADMPermissionError` в `exceptions.py` и распознавание явного отказа в `check_envelope` (`api.py`): код из набора `PERMISSION_DENIED_CODES` в `const.py` либо текст отказа с признаком отсутствия доступа; проверить, что код `5000` по-прежнему даёт `ADMSessionExpiredError`, а прочие неуспешные конверты — `ADMResponseError`; проверка: `python3 -m pytest tests/unit/test_api.py -q`, включая кейс на фикстуре `error_business.json` (`6300`, `operation not permitted`).
- [x] 1.2 Расширить `FakeADMClient` в `tests/conftest.py` возможностью вернуть заданную ответную ошибку (`ADMResponseError` или `ADMSessionExpiredError`) на конкретном эндпоинте без изменения остальных маршрутов; проверка: `python3 -m pytest -q` зелёный на существующих тестах.
- [x] 1.3 Перевести `_async_probe` в `config_flow.py` на причину `insufficient_privileges`: `ADMPermissionError` — всегда, прочий отказ чтения при ложном `login.is_admin` — тоже; фактический код и текст отказа писать в журнал `debug` без секретов и параметров запроса; проверка: тесты `tests/test_config_flow.py` для трёх случаев — `login_limited.json` вместе с `error_session_expired.json` даёт `{"base": "insufficient_privileges"}` и запись не создаётся, отказ `6300` у учётной записи администратора даёт ту же причину, ограниченная учётная запись с успешным чтением создаёт запись.
- [x] 1.4 Добавить строку `insufficient_privileges` в `strings.json`, `translations/en.json` и `translations/ru.json`; проверка: `python3 -m pytest tests/unit/test_translations.py -q` и совпадение `translations/en.json` со `strings.json` по блоку `config`.
- [x] 1.5 Описать в `README.md` требование к правам учётной записи (группа администраторов ADM) и поведение при их недостатке (ошибка настройки вместо непредвиденной ошибки); проверка: разделы «Требования» и «Настройка» содержат формулировку об ошибке «недостаточно прав».

## 2. Перенастройка подключения

- [x] 2.1 Вынести построение схемы полей подключения в общую функцию `config_flow.py` и переиспользовать её в `async_step_user` и `async_step_reconfigure` с подстановкой текущих значений записи; проверка: `test_user_flow_creates_entry` и тест формы перенастройки (поля предзаполнены данными записи) зелёные.
- [x] 2.2 Реализовать `async_step_reconfigure`: проверка параметров через `_async_probe`, обновление данных записи и её перезагрузка без создания новой записи; проверка: тест перенастройки меняет адрес и пароль, после чего запись содержит новые значения, `entry_id` не изменился, а поток завершился причиной `reconfigure_successful`.
- [x] 2.3 Реализовать привязку к тому же NAS по `design.md` D4: совпадение `unique_id`, миграция «адрес → серийный номер» с проверкой уникальности, отказ `wrong_device` при другом устройстве; проверка: три теста в `tests/test_config_flow.py` (успех, миграция, отказ), при отказе данные записи не меняются.
- [x] 2.4 Добавить причину `wrong_device` в `config.abort` (`strings.json`, `translations/en.json`, `translations/ru.json`); проверка: `python3 -m pytest tests/unit/test_translations.py -q` и наличие ключа в обоих переводах.
- [x] 2.5 Описать в `README.md` правку адреса, TLS и учётных данных существующей записи без удаления и ограничение «один NAS — одна запись»; проверка: раздел «Настройка» содержит порядок действий и упоминание отдельной записи для другого NAS.

## 3. Интеграционная проверка

- [x] 3.1 Прогнать обязательные проверки проекта: `python3 -m ruff check .`, `python3 -m ruff format --check .`, `python3 -m pytest tests/unit -q --confcutdir=tests/unit`, `python3 -m pytest -q`, `openspec validate --all --strict`; проверка: все команды завершаются успешно.
- [x] 3.2 Сверить `README.md` с кодом: число тестов и состав способностей настройки соответствуют фактическому набору; проверка: значения в разделе «Тесты» совпадают с выводом `python3 -m pytest -q`.

## 4. Workflow follow-up

- После выполнения задач архивировать изменение командой `openspec archive fix-connection-setup`, чтобы дельта `system-metrics` попала в основную спеку.
