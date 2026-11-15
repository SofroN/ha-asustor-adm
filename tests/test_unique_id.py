"""Стабильность идентификаторов сущностей (задача 4.4)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration
from homeassistant.helpers import entity_registry as er

from custom_components.asustor_adm.const import END_DISK_LIST


def _entries(hass, entry) -> dict[str, str]:
    registry = er.async_get(hass)
    return {
        item.entity_id: item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


async def test_unique_ids_use_serial_and_slot(hass, adm, entry) -> None:
    """Уникальные идентификаторы строятся из серийного номера и отсека."""
    await setup_integration(hass, entry)
    entries = _entries(hass, entry)

    unique_ids = set(entries.values())
    assert "SN012345678_disk_1_temperature" in unique_ids
    assert "SN012345678_volume_2_used_percent" in unique_ids
    assert "SN012345678_service_ssh" in unique_ids
    assert all("_sdc" not in item for item in unique_ids)


async def test_identifiers_survive_device_name_change(hass, adm, entry) -> None:
    """Переименование устройств sdX не создаёт новых сущностей."""
    await setup_integration(hass, entry)
    before = _entries(hass, entry)

    renamed = load_fixture("disks")
    for index, disk in enumerate(renamed["disks"]):
        disk["dev"] = ("sdx", "sdy", "sdz", "sdw")[index]
    adm.set_route(END_DISK_LIST, renamed)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = _entries(hass, entry)
    assert after == before


async def test_identifiers_survive_reconfiguration(hass, adm, entry) -> None:
    """Повторная настройка записи не меняет идентификаторы."""
    await setup_integration(hass, entry)
    before = _entries(hass, entry)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _entries(hass, entry) == before
