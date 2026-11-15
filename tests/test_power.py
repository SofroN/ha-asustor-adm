"""Управление питанием (задачи 8.3-8.5)."""

from __future__ import annotations

import json
import pathlib

import pytest
from helpers import load_fixture, setup_integration
from homeassistant.exceptions import HomeAssistantError

from custom_components.asustor_adm.exceptions import ADMPowerError

SHUTDOWN = "button.asustor_nas_adm_shutdown"
RESTART = "button.asustor_nas_adm_restart"
SLEEP = "button.asustor_nas_adm_sleep"
CPU = "sensor.asustor_nas_adm_cpu_usage"
COMPONENT = pathlib.Path(__file__).parents[1] / "custom_components" / "asustor_adm"


async def _press(hass, entity_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_shutdown_sends_command_once(hass, adm, entry) -> None:
    """Команда выключения отправляется по явному действию пользователя."""
    await setup_integration(hass, entry)
    assert adm.power_actions == []

    await _press(hass, SHUTDOWN)

    assert adm.power_actions == ["shutdown"]


async def test_restart_sends_command(hass, adm, entry) -> None:
    """Команда перезагрузки отправляется тем же путём."""
    await setup_integration(hass, entry)
    await _press(hass, RESTART)

    assert adm.power_actions == ["restart"]


async def test_entities_become_unavailable_without_retries(hass, adm, entry) -> None:
    """После команды сущности недоступны, повторов команды нет."""
    await setup_integration(hass, entry)
    await _press(hass, SHUTDOWN)

    assert hass.states.get(CPU).state == "unavailable"

    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()
    assert adm.power_actions == ["shutdown"]


async def test_recovery_after_device_returns(hass, adm, entry) -> None:
    """После ответа NAS работа восстанавливается без вмешательства."""
    await setup_integration(hass, entry)
    await _press(hass, RESTART)
    assert hass.states.get(CPU).state == "unavailable"

    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(CPU).state == "3.8"
    assert adm.power_actions == ["restart"]


async def test_power_command_error_is_reported(hass, adm, entry) -> None:
    """Отказ команды питания показывается пользователю без повторов."""
    await setup_integration(hass, entry)
    adm.fail_power = ADMPowerError("command rejected")

    with pytest.raises(HomeAssistantError):
        await _press(hass, SHUTDOWN)

    assert hass.states.get(SHUTDOWN).state != "unavailable"
    assert adm.power_actions == []


async def test_sleep_button_sends_suspend(hass, adm, entry) -> None:
    """Кнопка сна отправляет команду suspend, если модель её поддерживает."""
    adm.login_payload = load_fixture("login_suspend")
    await setup_integration(hass, entry)

    await _press(hass, SLEEP)

    assert adm.power_actions == ["suspend"]


def test_documentation_warns_about_service_interruption() -> None:
    """Предупреждение о прерывании служб есть в README и в описании кнопок."""
    readme = (COMPONENT.parents[1] / "README.md").read_text(encoding="utf-8")
    assert "прерывают работу всех служб NAS" in readme

    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    buttons = strings["entity"]["button"]
    for key in ("shutdown", "restart"):
        assert "services" in buttons[key]["description"].lower()

    russian = json.loads(
        (COMPONENT / "translations" / "ru.json").read_text(encoding="utf-8")
    )
    for key in ("shutdown", "restart"):
        assert "служб" in russian["entity"]["button"][key]["description"]
