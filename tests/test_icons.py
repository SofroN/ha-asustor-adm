"""Иконки сущностей: явные только там, где `device_class` не различает смысл."""

from __future__ import annotations

from typing import Any

from helpers import load_fixture, setup_integration


def _icon(hass: Any, entity_id: str) -> str | None:
    """Вернуть иконку, объявленную самой сущностью, а не выведенную из класса."""
    domain = entity_id.split(".", 1)[0]
    entity = hass.data["entity_components"][domain].get_entity(entity_id)
    assert entity is not None, entity_id
    return entity.icon


async def test_utilization_sensors_have_icons(hass, adm, entry) -> None:
    """Проценты без `device_class` получают явные иконки."""
    await setup_integration(hass, entry)

    assert _icon(hass, "sensor.asustor_nas_adm_memory_utilization") == "mdi:memory"
    assert (
        _icon(hass, "sensor.asustor_nas_adm_volume_1_utilization") == "mdi:chart-donut"
    )
    assert (
        _icon(hass, "sensor.asustor_nas_adm_external_disk_usb2_used")
        == "mdi:chart-donut"
    )


async def test_direction_sensors_have_distinct_icons(hass, adm, entry) -> None:
    """Приём и передача, чтение и запись различаются иконкой."""
    await setup_integration(hass, entry)

    assert (
        _icon(hass, "sensor.asustor_nas_adm_network_lan1_receive")
        == "mdi:download-network"
    )
    assert (
        _icon(hass, "sensor.asustor_nas_adm_network_lan1_transmit")
        == "mdi:upload-network"
    )
    assert _icon(hass, "sensor.asustor_nas_adm_disk_1_read") == "mdi:download"
    assert _icon(hass, "sensor.asustor_nas_adm_disk_1_write") == "mdi:upload"


async def test_power_buttons_have_icons(hass, adm, entry) -> None:
    """Кнопке питания задана иконка её действия, а не общий символ нажатия."""
    adm.login_payload = load_fixture("login_suspend")
    await setup_integration(hass, entry)

    assert _icon(hass, "button.asustor_nas_adm_shutdown") == "mdi:power"
    assert _icon(hass, "button.asustor_nas_adm_restart") == "mdi:restart"
    assert _icon(hass, "button.asustor_nas_adm_sleep") == "mdi:power-sleep"


async def test_device_class_icons_are_not_duplicated(hass, adm, entry) -> None:
    """Сущности с точным `device_class` иконку явно не задают."""
    await setup_integration(hass, entry)

    for entity_id in (
        "sensor.asustor_nas_adm_memory_used",
        "sensor.asustor_nas_adm_cpu_temperature",
        "sensor.asustor_nas_adm_volume_1_capacity",
        "sensor.asustor_nas_adm_disk_1_temperature",
        "sensor.asustor_nas_adm_external_disk_usb2_capacity",
        "binary_sensor.asustor_nas_adm_adm_update_available",
    ):
        assert _icon(hass, entity_id) is None, entity_id
