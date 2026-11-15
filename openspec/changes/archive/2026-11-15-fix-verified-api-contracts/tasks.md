# Tasks

## 1. Параметры контракта в эндпоинтах

- [x] 1.1 Добавить в `Endpoint` (`const.py`) поле `params` и передавать его в query каждого запроса в `ADMClient._async_send`; проверка: `python3 -m pytest tests/unit/test_api.py -q` — запрос к `services/windows.cgi` содержит `tab=cifs`, запрос к `onlineuser.cgi` содержит `sort`, `ascend`, `start`, `limit`.
- [x] 1.2 Проставить `tab` для SMB/CIFS, NFS, FTP, WebDAV и SNMP по значениям из интерфейса ADM; проверить, что уникальность `SERVICE_ENDPOINTS` и число запросов цикла не изменились; проверка: `python3 -m pytest tests/unit/test_const.py -q` — у пяти служб ровно один параметр `tab` с ожидаемым значением, у SSH, SFTP, rsync и TFTP параметров нет, `len(SERVICE_ENDPOINTS) == 8`.
- [x] 1.3 Проставить параметры постраничности эндпоинту списка сессий; проверка: `python3 -m pytest tests/unit/test_const.py -q` — `END_SESSIONS.params` равен `sort=0, ascend=0, start=0, limit=100`.
- [x] 1.4 Проверить исправление на живом ADM 5.1.4.DM62 (демо-портал ASUSTOR): все девять служб возвращают состояния, число сессий читается; проверка: прогон `ADMClient` и `parse_service_state` против демо-портала даёт `smb=True, nfs=True, ftp=False, webdav=False, ssh=True, sftp=True, rsync=False, snmp=False, tftp=False` и ненулевое число сессий.

## 2. Двухфакторная авторизация

- [x] 2.1 Передавать `two-step-auth=true` в форме авторизации и распознавать требование кода по `error_code == 5034`, убрав перебор имён полей; проверка: `python3 -m pytest tests/unit/test_api.py -q` — форма авторизации содержит `two-step-auth=true`, ответ `{"success": false, "error_code": 5034}` даёт `ADMTwoFactorRequiredError`.
- [x] 2.2 Привести фикстуру `login_two_factor` к фактической форме ответа и отметить её происхождение в `tests/fixtures/README.md`; проверка: `python3 -m pytest tests/test_config_flow.py -q` — настройка с такой фикстурой возвращает `{"base": "two_factor"}` и запись не создаётся.
- [x] 2.3 Повторить правило распознавания в подменном клиенте `tests/conftest.py`, чтобы тесты видели то же поведение, что настоящий клиент; проверка: `python3 -m pytest -q` зелёный.

## 3. Коды проверки обновлений

- [x] 3.1 Переименовать константы по подтверждённым значениям (`5005` — нет связи с сервером обновлений, `6209` — последняя версия, `6215` — та же версия), заменить набор «проверка недоступна» на «новее нет» и зафиксировать в комментарии контекстность кодов; проверка: `python3 -m pytest tests/unit/test_const.py -q` — `ERROR_CODES` содержит `{5000, 5005, 5034, 6209, 6215, 6300}`, ссылок на `ERR_UPDATE_NO_DATA` и `UPDATE_UNAVAILABLE_CODES` в коде нет.

## 4. Документация и проверки

- [x] 4.1 Обновить `CHANGELOG.md` разделом «Исправлено» о службах, сессиях, двухфакторной авторизации и кодах обновлений; проверка: `sed -n '/## \[Unreleased\]/,/## \[0.1.0\]/p' CHANGELOG.md` содержит четыре записи.
- [x] 4.2 Сверить число тестов в `README.md` с фактическим выводом полного набора; проверка: значения в разделе «Тесты» совпадают с `python3 -m pytest -q`.
- [x] 4.3 Прогнать обязательные проверки: `python3 -m ruff check .`, `python3 -m ruff format --check .`, `python3 -m pytest tests/unit -q --confcutdir=tests/unit`, `python3 -m pytest -q`, `openspec validate --all --strict`; проверка: все команды завершаются успешно.

## Workflow follow-up

- Архивировать изменение командой `openspec archive 2026-11-15-fix-verified-api-contracts` после приёмки, чтобы дельты `services-status` и `system-metrics` попали в основные спеки. Изменения `fix-connection-setup` и `fix-firmware-update-signal` к этому моменту уже архивированы: они тоже правят требование «Настройка подключения».
