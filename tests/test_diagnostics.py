"""Диагностика и отсутствие секретов (задачи 3.4, 9.4)."""

from __future__ import annotations

import json
import logging

from helpers import setup_integration

from custom_components.asustor_adm.const import (
    END_ACTIVITY,
    END_DISK_LIST,
    END_SYSINFO,
    END_VOLUME_LIST,
)
from custom_components.asustor_adm.diagnostics import (
    async_get_config_entry_diagnostics,
)

FORBIDDEN = ("secret", "TEST-SID", "SANITIZED", "SN012345678", "nas.example.com")


async def test_diagnostics_hides_secrets(hass, adm, entry) -> None:
    """В выгрузке нет пароля, sid, паспорта и серийного номера."""
    await setup_integration(hass, entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diagnostics, ensure_ascii=False, default=str)

    for forbidden in FORBIDDEN:
        assert forbidden not in text, f"в диагностике найден секрет {forbidden}"
    assert "sid=" not in text
    assert "password" in text
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"


async def test_diagnostics_lists_services(hass, adm, entry) -> None:
    """В выгрузке присутствуют обнаруженные сервисы и их состояния."""
    await setup_integration(hass, entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    services = diagnostics["services"]
    assert services["smb"] is True
    assert services["ssh"] is False
    assert len(services) == 9
    assert diagnostics["firmware"]["installed_version"] == "5.1.4.RM62"
    assert diagnostics["counts"]["volumes"] == 2
    assert diagnostics["counts"]["disks"] == 4
    assert diagnostics["permissions"]["is_admin"] is True


async def test_diagnostics_reports_degraded_requests(hass, adm, entry) -> None:
    """Отказ одного запроса виден в диагностике как ухудшение данных."""
    await setup_integration(hass, entry)
    adm.failing_paths.add(END_ACTIVITY.path)
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    degraded = diagnostics["coordinators"]["fast"]["degraded_requests"]
    assert END_ACTIVITY.path in degraded
    assert diagnostics["coordinators"]["fast"]["last_update_success"] is True


async def test_diagnostics_reports_full_failure(hass, adm, entry) -> None:
    """Полный отказ быстрого цикла виден как недоступность устройства."""
    await setup_integration(hass, entry)
    adm.failing_paths.update(
        {
            END_ACTIVITY.path,
            END_SYSINFO.path,
            END_VOLUME_LIST.path,
            END_DISK_LIST.path,
        }
    )
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["coordinators"]["fast"]["last_update_success"] is False
    assert diagnostics["coordinators"]["fast"]["last_error"]


async def test_debug_log_has_no_secrets(hass, adm, entry) -> None:
    """Журнал отладочного уровня не содержит пароля и идентификатора сессии."""
    messages: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: messages.append(record.getMessage())
    logger = logging.getLogger("custom_components.asustor_adm")
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        await setup_integration(hass, entry)
        await entry.runtime_data.slow.async_refresh()
        await hass.async_block_till_done()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    text = "\n".join(messages)
    assert messages, "интеграция не пишет в журнал ни одной записи"
    for forbidden in ("secret", "TEST-SID", "SANITIZED", "sid=", "passport"):
        assert forbidden not in text
