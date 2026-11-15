"""Тома, RAID и диски (задачи 6.1-6.3)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.asustor_adm.const import (
    END_DISK_LIST,
    END_DISK_SMART,
    END_VOLUME_GET,
    END_VOLUME_LIST,
)

CAPACITY_1 = "sensor.asustor_nas_adm_volume_1_capacity"
USED_1 = "sensor.asustor_nas_adm_volume_1_used_space"
UTILIZATION_1 = "sensor.asustor_nas_adm_volume_1_utilization"
CAPACITY_2 = "sensor.asustor_nas_adm_volume_2_capacity"
PROBLEM_1 = "binary_sensor.asustor_nas_adm_volume_1_problem"
PROBLEM_2 = "binary_sensor.asustor_nas_adm_volume_2_problem"


async def test_volume_capacity_used_and_share(hass, adm, entry) -> None:
    """Для каждого тома публикуются ёмкость, занятое место и заполнение."""
    await setup_integration(hass, entry)

    assert hass.states.get(CAPACITY_1).state == "7387.94"
    assert hass.states.get(USED_1).state == "4417.06"
    assert hass.states.get(UTILIZATION_1).state == "59.8"
    assert hass.states.get(CAPACITY_2).state == "1828.47"
    assert hass.states.get(CAPACITY_1).attributes["device_class"] == "data_size"
    assert hass.states.get(CAPACITY_1).attributes["unit_of_measurement"] == "GiB"


async def test_raid_attributes_on_volume(hass, adm, entry) -> None:
    """Сведения RAID публикуются атрибутами сущности тома."""
    await setup_integration(hass, entry)

    attributes = hass.states.get(CAPACITY_2).attributes
    assert attributes["level"] == "raid1"
    assert attributes["members"] == 2
    assert attributes["has_spare"] is True

    assert "level" not in hass.states.get(CAPACITY_1).attributes


async def test_volume_without_used_space(hass, adm, entry) -> None:
    """Том без занятого объёма публикует ёмкость без доли заполнения."""
    adm.set_route(END_VOLUME_LIST, load_fixture("volumes_without_used"))
    await setup_integration(hass, entry)

    assert hass.states.get(CAPACITY_1).state == "7387.94"
    assert hass.states.get(UTILIZATION_1).state == "unavailable"


async def test_degraded_volume_reports_problem(hass, adm, entry) -> None:
    """Деградация массива даёт проблему тома."""
    adm.set_route(END_VOLUME_LIST, load_fixture("volumes_degraded"))
    adm.set_route_by_params(END_VOLUME_GET, "vid", 2, load_fixture("volume_2_degraded"))
    await setup_integration(hass, entry)

    assert hass.states.get(PROBLEM_1).state == "off"
    assert hass.states.get(PROBLEM_2).state == "on"


async def test_three_volumes_have_three_entities_each(hass, adm, entry) -> None:
    """Три тома дают по три сущности объёма, места и заполнения."""
    adm.set_route(END_VOLUME_LIST, load_fixture("volumes_three"))
    await setup_integration(hass, entry)

    for vid in (1, 2, 3):
        assert (
            hass.states.get(f"sensor.asustor_nas_adm_volume_{vid}_capacity") is not None
        )
        assert (
            hass.states.get(f"sensor.asustor_nas_adm_volume_{vid}_used_space")
            is not None
        )
        assert (
            hass.states.get(f"sensor.asustor_nas_adm_volume_{vid}_utilization")
            is not None
        )


async def test_removed_disk_makes_entities_unavailable(hass, adm, entry) -> None:
    """Исчезнувший из ответа диск делает свои сущности недоступными."""
    await setup_integration(hass, entry)
    assert hass.states.get("sensor.asustor_nas_adm_disk_3_temperature").state == "33.0"

    adm.set_route(END_DISK_LIST, load_fixture("disks_two"))
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.asustor_nas_adm_disk_3_temperature").state == (
        "unavailable"
    )
    assert hass.states.get("sensor.asustor_nas_adm_disk_1_temperature").state == "40.0"


async def test_missing_volume_makes_entities_unavailable(hass, adm, entry) -> None:
    """Исчезнувший том делает связанные сущности недоступными."""
    await setup_integration(hass, entry)
    assert hass.states.get(PROBLEM_2).state == "off"

    adm.set_route(END_VOLUME_LIST, load_fixture("volumes_single"))
    await entry.runtime_data.fast.async_refresh()
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(CAPACITY_2).state == "unavailable"
    assert hass.states.get(PROBLEM_2).state == "unavailable"
    assert hass.states.get(CAPACITY_1).state == "7387.94"


async def test_disk_temperatures_and_details(hass, adm, entry) -> None:
    """Температура и сведения публикуются по каждому диску."""
    await setup_integration(hass, entry)

    state = hass.states.get("sensor.asustor_nas_adm_disk_1_temperature")
    assert state.state == "40.0"
    assert state.attributes["model"] == "ST2000DM008-2FR102"
    assert state.attributes["slot"] == 1
    assert state.attributes["firmware"] == "0001"
    assert hass.states.get("sensor.asustor_nas_adm_disk_4_temperature").state == "37.0"


async def test_disk_outside_volume_is_published(hass, adm, entry) -> None:
    """Диск, не входящий в том, всё равно публикуется как установленный."""
    await setup_integration(hass, entry)
    state = hass.states.get("sensor.asustor_nas_adm_disk_3_temperature")

    assert state.state == "33.0"
    assert "volume" not in state.attributes


async def test_disk_without_temperature_has_no_entity(hass, adm, entry) -> None:
    """Диск без датчика температуры не создаёт сущность температуры."""
    adm.set_route(END_DISK_LIST, load_fixture("disks_no_temperature"))
    await setup_integration(hass, entry)

    assert hass.states.get("sensor.asustor_nas_adm_disk_2_temperature") is None
    assert hass.states.get("sensor.asustor_nas_adm_disk_1_temperature") is not None


async def test_smart_attributes_are_requested_on_demand(hass, adm, entry) -> None:
    """Атрибуты SMART запрашиваются по требованию, а не в цикле опроса."""
    assert await async_setup_component(hass, "homeassistant", {})
    await setup_integration(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "asustor_adm", "SN012345678_disk_1_smart"
    )
    assert entity_id is not None
    assert (END_DISK_SMART.path, END_DISK_SMART.act) not in adm.requests

    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "17678.7"
    assert state.attributes["reallocated_sectors"] == 0
    assert state.attributes["pending_sectors"] == 0
    assert state.attributes["temperature"] == 40
    assert state.attributes["Reallocated_Sector_Ct"] == "0"


async def test_smart_request_failure_keeps_disk_entity(hass, adm, entry) -> None:
    """Ошибка запроса SMART не отражается на сущностях диска."""
    assert await async_setup_component(hass, "homeassistant", {})
    await setup_integration(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "asustor_adm", "SN012345678_disk_1_smart"
    )
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    adm.failing_paths.add(END_DISK_SMART.path)
    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.asustor_nas_adm_disk_1_temperature").state == "40.0"
    assert hass.states.get("sensor.asustor_nas_adm_disk_1_read").state == "0.0"
