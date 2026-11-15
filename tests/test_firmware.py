"""Прошивка ADM и обновления App Central (задачи 2.2, 3.1-3.3, 8.1-8.2)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import load_fixture, setup_integration
from homeassistant.exceptions import HomeAssistantError

from custom_components.asustor_adm.const import END_APP_UPDATES, END_FIRMWARE

UPDATE = "binary_sensor.asustor_nas_adm_adm_update_available"
APP_UPDATES = "sensor.asustor_nas_adm_app_central_updates"
FIRMWARE_UPDATE = "update.asustor_nas_adm_adm_firmware"

INSTALLED = "5.1.4.RM62"
TARGET = "5.1.5.RN11"


def _firmware_payload(target: str | None, *, flag: bool = True) -> dict[str, Any]:
    """Собрать ответ ADM с заданной целевой версией."""
    payload: dict[str, Any] = {
        "last_update_time": "2026/11/14",
        "update_available_notification": flag,
        "installed_version": INSTALLED,
        "nas_model": "AS3304T",
    }
    if target is not None:
        payload["new_version"] = target
    return payload


async def test_update_unavailable_without_target(hass, adm, entry) -> None:
    """Флаг уведомления без целевой версии не даёт «обновление доступно»."""
    await setup_integration(hass, entry)
    state = hass.states.get(UPDATE)

    assert state is not None
    assert state.state == "unavailable"


async def test_update_unavailable_when_flag_cleared(hass, adm, entry) -> None:
    """Снятый флаг уведомления тоже не подтверждает обновление."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_up_to_date"))
    await setup_integration(hass, entry)

    assert hass.states.get(UPDATE).state == "unavailable"


async def test_update_available_with_confirmed_target(hass, adm, entry) -> None:
    """Подтверждённая более новая целевая версия включает признак обновления."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)
    state = hass.states.get(UPDATE)

    assert state.state == "on"
    assert state.attributes["installed_version"] == INSTALLED
    assert state.attributes["target_version"] == TARGET
    assert state.attributes["notification_flag"] is True
    assert state.attributes["last_check_time"] == "2026/11/14"


@pytest.mark.parametrize("target", [INSTALLED, "5.1.4.rm62", "5.1.3.RN1"])
async def test_update_off_when_target_not_newer(hass, adm, entry, target: str) -> None:
    """Равная установленной или старше неё целевая версия даёт «обновлений нет»."""
    adm.set_route(END_FIRMWARE, _firmware_payload(target))
    await setup_integration(hass, entry)

    state = hass.states.get(UPDATE)
    assert state.state == "off"
    # При известном состоянии сведения проверки видны как атрибуты.
    assert state.attributes["notification_flag"] is True
    assert state.attributes["last_check_time"] == "2026/11/14"
    # Сущность обновления при такой цели не создаётся.
    assert hass.states.get(FIRMWARE_UPDATE) is None


async def test_update_attributes_omit_missing_check_fields(hass, adm, entry) -> None:
    """Отсутствующие поля проверки не публикуются как false или пустая строка."""
    adm.set_route(END_FIRMWARE, {"installed_version": INSTALLED, "new_version": TARGET})
    await setup_integration(hass, entry)
    state = hass.states.get(UPDATE)

    assert state.state == "on"
    assert state.attributes["target_version"] == TARGET
    assert "notification_flag" not in state.attributes
    assert "last_check_time" not in state.attributes


async def test_update_unavailable_when_target_not_comparable(hass, adm, entry) -> None:
    """Несравнимая целевая версия оставляет признак неизвестным."""
    adm.set_route(END_FIRMWARE, _firmware_payload("5.1.4.2"))
    await setup_integration(hass, entry)

    assert hass.states.get(UPDATE).state == "unavailable"


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
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)
    assert hass.states.get(UPDATE).state == "on"

    adm.set_route(END_FIRMWARE, load_fixture(fixture))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(UPDATE)
    assert state.state == "on"
    assert state.attributes["target_version"] == TARGET
    assert state.attributes["last_check_error"] is not None
    assert hass.states.get("sensor.asustor_nas_adm_active_sessions").state == "1"


async def test_success_without_target_drops_confirmed_value(hass, adm, entry) -> None:
    """Успешный ответ без целевой версии не наследует прошлое обновление."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)
    assert hass.states.get(UPDATE).state == "on"

    adm.set_route(END_FIRMWARE, load_fixture("firmware"))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(UPDATE).state == "unavailable"


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
    """При подтверждённой более новой цели создаётся сущность обновления."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)

    state = hass.states.get(FIRMWARE_UPDATE)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["installed_version"] == INSTALLED
    assert state.attributes["latest_version"] == TARGET


async def test_update_entity_off_for_equal_target(hass, adm, entry) -> None:
    """Равная установленной целевая версия не показывает обновление."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)
    assert hass.states.get(FIRMWARE_UPDATE).state == "on"

    adm.set_route(END_FIRMWARE, _firmware_payload(INSTALLED))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(FIRMWARE_UPDATE)
    assert state.state == "off"
    assert state.attributes["latest_version"] == INSTALLED


async def test_update_entity_unavailable_without_target(hass, adm, entry) -> None:
    """Ответ без целевой версии делает созданную сущность недоступной."""
    adm.set_route(END_FIRMWARE, load_fixture("firmware_with_target"))
    await setup_integration(hass, entry)

    adm.set_route(END_FIRMWARE, load_fixture("firmware"))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(FIRMWARE_UPDATE).state == "unavailable"


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
