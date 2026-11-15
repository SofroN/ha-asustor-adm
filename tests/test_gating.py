"""Гейтирование сущностей по возможностям устройства (задача 4.3)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration

from custom_components.asustor_adm.const import END_SYSINFO


async def test_limited_account_has_no_power_buttons(hass, adm, entry) -> None:
    """Без прав администратора кнопки питания не создаются."""
    adm.login_payload = load_fixture("login_limited")
    await setup_integration(hass, entry)

    assert hass.states.get("button.asustor_nas_adm_shutdown") is None
    assert hass.states.get("button.asustor_nas_adm_restart") is None
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage") is not None


async def test_administrator_has_power_buttons(hass, adm, entry) -> None:
    """Администратор получает кнопки выключения и перезагрузки."""
    await setup_integration(hass, entry)

    assert hass.states.get("button.asustor_nas_adm_shutdown") is not None
    assert hass.states.get("button.asustor_nas_adm_restart") is not None


async def test_sleep_button_requires_device_support(hass, adm, entry) -> None:
    """Кнопка сна не создаётся, если устройство не сообщает о поддержке."""
    await setup_integration(hass, entry)
    assert hass.states.get("button.asustor_nas_adm_sleep") is None


async def test_sleep_button_appears_with_support(hass, adm, entry) -> None:
    """Кнопка сна создаётся, когда ADM сообщает о поддержке."""
    adm.login_payload = load_fixture("login_suspend")
    await setup_integration(hass, entry)

    assert hass.states.get("button.asustor_nas_adm_sleep") is not None


async def test_fans_follow_reported_array(hass, adm, entry) -> None:
    """Число сущностей кулеров соответствует длине массива."""
    adm.set_route(END_SYSINFO, load_fixture("sysinfo_two_fans"))
    await setup_integration(hass, entry)

    assert hass.states.get("sensor.asustor_nas_adm_fan_1_speed").state == "776.0"
    assert hass.states.get("sensor.asustor_nas_adm_fan_2_speed").state == "812.0"


async def test_missing_temperature_skips_entity(hass, adm, entry) -> None:
    """Модель без датчика температуры не создаёт сущность температуры."""
    adm.set_route(END_SYSINFO, load_fixture("sysinfo_no_temperature"))
    await setup_integration(hass, entry)

    assert hass.states.get("sensor.asustor_nas_adm_cpu_temperature") is None
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage") is not None
