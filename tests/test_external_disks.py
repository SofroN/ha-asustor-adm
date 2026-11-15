"""Внешние USB-диски (задача 7.4)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration

from custom_components.asustor_adm.const import END_EXT_DISK

CONNECTED = "binary_sensor.asustor_nas_adm_external_disk_usb2_connected"
READY = "binary_sensor.asustor_nas_adm_external_disk_usb2_ready"
CAPACITY = "sensor.asustor_nas_adm_external_disk_usb2_capacity"
FREE = "sensor.asustor_nas_adm_external_disk_usb2_free_space"
USED = "sensor.asustor_nas_adm_external_disk_usb2_used"


async def test_connected_disk_entities(hass, adm, entry) -> None:
    """Подключённый диск получает признаки и сенсоры объёма."""
    await setup_integration(hass, entry)

    assert hass.states.get(CONNECTED).state == "on"
    assert hass.states.get(READY).state == "on"
    assert hass.states.get(CAPACITY).state == "1862.98"
    assert hass.states.get(FREE).state == "70.86"
    assert hass.states.get(USED).state == "96.2"
    assert hass.states.get(CAPACITY).attributes["vendor"] == "WDC"
    assert hass.states.get(CAPACITY).attributes["connection_type"] == "USB 3.2 Gen 1"
    assert hass.states.get(CAPACITY).attributes["filesystem"] == "ntfs"


async def test_no_external_disks_no_entities(hass, adm, entry) -> None:
    """Без внешних дисков сущности не создаются и опрос не падает."""
    adm.set_route(END_EXT_DISK, load_fixture("extdisks_empty"))
    await setup_integration(hass, entry)

    assert hass.states.get(CONNECTED) is None
    assert hass.states.get(CAPACITY) is None
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage").state == "3.8"


async def test_ejecting_disk_is_not_ready(hass, adm, entry) -> None:
    """Диск в состоянии извлечения не готов к работе."""
    adm.set_route(END_EXT_DISK, load_fixture("extdisks_ejecting"))
    await setup_integration(hass, entry)

    assert hass.states.get(READY).state == "off"
    assert hass.states.get(CAPACITY).state == "1862.98"


async def test_second_disk_is_added(hass, adm, entry) -> None:
    """Появление второго диска создаёт его сущности без перезапуска."""
    adm.set_route(END_EXT_DISK, load_fixture("extdisks_single"))
    await setup_integration(hass, entry)
    assert (
        hass.states.get("binary_sensor.asustor_nas_adm_external_disk_usb31_connected")
        is None
    )

    adm.set_route(END_EXT_DISK, load_fixture("extdisks"))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert (
        hass.states.get(
            "binary_sensor.asustor_nas_adm_external_disk_usb31_connected"
        ).state
        == "on"
    )
    assert (
        hass.states.get("sensor.asustor_nas_adm_external_disk_usb31_capacity").state
        == "931.51"
    )
    assert hass.states.get(CONNECTED).state == "on"


async def test_disconnected_disk_becomes_unavailable(hass, adm, entry) -> None:
    """После отключения диска его сущности становятся недоступными."""
    await setup_integration(hass, entry)
    assert hass.states.get(CONNECTED).state == "on"

    adm.set_route(END_EXT_DISK, load_fixture("extdisks_empty"))
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(CONNECTED).state == "unavailable"
    assert hass.states.get(CAPACITY).state == "unavailable"
