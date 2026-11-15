"""Сетевой обмен и скорости дисков (задачи 5.4, 5.5)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration

from custom_components.asustor_adm.const import END_ACTIVITY

RECEIVE = "sensor.asustor_nas_adm_network_lan1_receive"
TRANSMIT = "sensor.asustor_nas_adm_network_lan1_transmit"
DISK_READ = "sensor.asustor_nas_adm_disk_1_read"
DISK_WRITE = "sensor.asustor_nas_adm_disk_1_write"


async def test_network_directions_follow_adm_fields(hass, adm, entry) -> None:
    """Приём отражает данные, поступающие на NAS, передача — отдаваемые."""
    adm.set_route(END_ACTIVITY, load_fixture("activity_write"))
    await setup_integration(hass, entry)

    assert hass.states.get(RECEIVE).state == "21522.0"
    assert hass.states.get(TRANSMIT).state == "226.0"

    adm.set_route(END_ACTIVITY, load_fixture("activity_read"))
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(TRANSMIT).state == "21541.0"
    assert hass.states.get(RECEIVE).state == "95.0"


async def test_network_sensors_are_enabled_with_data_rate_class(
    hass, adm, entry
) -> None:
    """Сетевые сенсоры включены по умолчанию и участвуют в статистике."""
    await setup_integration(hass, entry)
    state = hass.states.get(RECEIVE)

    assert state.attributes["device_class"] == "data_rate"
    assert state.attributes["state_class"] == "measurement"
    assert state.attributes["unit_of_measurement"] == "kB/s"


async def test_disabled_interface_has_no_entities(hass, adm, entry) -> None:
    """Для выключенного интерфейса сущности не создаются."""
    adm.set_route(END_ACTIVITY, load_fixture("activity_no_network"))
    await setup_integration(hass, entry)

    assert hass.states.get(RECEIVE) is None
    assert hass.states.get(TRANSMIT) is None


async def test_disk_speeds_are_published_per_disk(hass, adm, entry) -> None:
    """Скорости чтения и записи публикуются по каждому диску."""
    adm.set_route(END_ACTIVITY, load_fixture("activity_write"))
    await setup_integration(hass, entry)

    assert hass.states.get(DISK_WRITE).state == "22155.0"
    assert hass.states.get("sensor.asustor_nas_adm_disk_2_write").state == "12018.0"
    assert hass.states.get(DISK_READ).state == "0.0"
    assert hass.states.get(DISK_WRITE).attributes["state_class"] == "measurement"
    assert hass.states.get(DISK_WRITE).attributes["device_class"] == "data_rate"


async def test_cache_served_read_stays_zero_and_available(hass, adm, entry) -> None:
    """Нулевое чтение из кэша не делает сущности недоступными."""
    adm.set_route(END_ACTIVITY, load_fixture("activity_cache_hit"))
    await setup_integration(hass, entry)

    assert hass.states.get(DISK_READ).state == "0.0"
    assert hass.states.get(DISK_READ).state != "unavailable"
    assert hass.states.get(TRANSMIT).state == "21541.0"
