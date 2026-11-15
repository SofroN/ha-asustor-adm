"""Прошивка ADM и обновления App Central (задачи 7.3, 8.1, 8.2)."""

from __future__ import annotations

import pytest
from helpers import load_fixture, setup_integration
from homeassistant.exceptions import HomeAssistantError

from custom_components.asustor_adm.const import END_APP_UPDATES, END_FIRMWARE

UPDATE = "binary_sensor.asustor_nas_adm_adm_update_available"
APP_UPDATES = "sensor.asustor_nas_adm_app_central_updates"
FIRMWARE_UPDATE = "update.asustor_nas_adm_adm_firmware"


async def test_update_available(hass, adm, entry) -> None:
    """Признак доступного обновления берётся из локальных данных ADM."""
    await setup_integration(hass, entry)
    state = hass.states.get(UPDATE)

    assert state.state == "on"
    assert state.attributes["device_class"] == "update"
    assert state.attributes["installed_version"] == "5.1.4.RM62"


async def test_no_update(hass, adm, entry) -> None:
    """Отсутствие обновлений даёт состояние «выключено»."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_up_to_date"))
    await setup_integration(hass, entry)

    assert hass.states.get(UPDATE).state == "off"


@pytest.mark.parametrize(
    "fixture",
    [
        "firmware_unavailable",
        "firmware_no_data",
        "firmware_not_available",
        "firmware_success_false",
    ],
)
async def test_unavailable_check_keeps_last_value(
    hass, adm, entry, fixture: str
) -> None:
    """Неудачная проверка сохраняет последнее подтверждённое значение."""
    await setup_integration(hass, entry)
    assert hass.states.get(UPDATE).state == "on"

    adm.set_route(END_FIRMWARE, load_fixture(fixture))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(UPDATE)
    assert state.state == "on"
    assert state.attributes["last_check_error"] is not None
    assert hass.states.get("sensor.asustor_nas_adm_active_sessions").state == "1"


async def test_app_updates_count(hass, adm, entry) -> None:
    """Счётчик обновлений приложений публикуется как число."""
    adm.set_route(END_APP_UPDATES, load_fixture("appcentral_updates"))
    await setup_integration(hass, entry)

    assert hass.states.get(APP_UPDATES).state == "3"


async def test_app_central_failure_isolated(hass, adm, entry) -> None:
    """Ошибка App Central делает недоступным только свой сенсор."""
    await setup_integration(hass, entry)
    adm.set_route(END_APP_UPDATES, {"success": False, "error_code": 6300})
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(APP_UPDATES).state == "unavailable"
    assert hass.states.get("sensor.asustor_nas_adm_active_sessions").state == "1"
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage").state == "3.8"


async def test_update_entity_needs_confirmed_target(hass, adm, entry) -> None:
    """Без подтверждённой целевой версии сущность обновления не создаётся."""
    await setup_integration(hass, entry)
    assert hass.states.get(FIRMWARE_UPDATE) is None


async def test_update_entity_created_with_target(hass, adm, entry) -> None:
    """При подтверждённой целевой версии создаётся сущность обновления."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)

    state = hass.states.get(FIRMWARE_UPDATE)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["installed_version"] == "5.1.4.RM62"
    assert state.attributes["latest_version"] == "5.1.5.RN11"


async def test_install_is_refused(hass, adm, entry) -> None:
    """Установка обновления из Home Assistant отклоняется без команды на NAS."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)
    requests_before = list(adm.requests)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "update",
            "install",
            {"entity_id": FIRMWARE_UPDATE},
            blocking=True,
        )

    assert adm.requests == requests_before
