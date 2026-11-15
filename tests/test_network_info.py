"""Сетевые сведения NAS: IP-адрес и внешний IP (D13)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration
from homeassistant.helpers import entity_registry as er

IP_ADDRESS = "sensor.asustor_nas_adm_ip_address"
WAN_ADDRESS = "sensor.asustor_nas_adm_wan_ip_address"


async def test_ip_address_and_attributes(hass, adm, entry) -> None:
    """IP-адрес берётся из активного интерфейса, остальное — в атрибутах."""
    await setup_integration(hass, entry)
    state = hass.states.get(IP_ADDRESS)

    assert state is not None
    assert state.state == "192.168.77.5"
    assert state.attributes["mac"] == "00:00:5e:00:53:a7"
    assert state.attributes["gateway"] == "192.168.77.1"
    assert state.attributes["dns"] == ["192.168.77.3", "77.88.8.8"]
    assert state.attributes["ipv6"] == "fe80::200:5eff:fe00:53a7/64"


async def test_wan_address_is_disabled_by_default(hass, adm, entry) -> None:
    """Внешний IP создаётся отключённым как диагностический сенсор."""
    await setup_integration(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "asustor_adm", "SN012345678_wan_ip"
    )

    assert entity_id is not None
    assert registry.async_get(entity_id).disabled_by is not None
    assert registry.async_get(entity_id).entity_category == "diagnostic"
    assert hass.states.get(entity_id) is None


async def test_wan_address_after_enabling(hass, adm, entry) -> None:
    """После включения сущность публикует внешний адрес."""
    await setup_integration(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "asustor_adm", "SN012345678_wan_ip"
    )
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "203.0.113.10"


async def test_network_request_failure_keeps_other_entities(hass, adm, entry) -> None:
    """Отказ запроса сети делает недоступным только IP-сенсор."""
    from custom_components.asustor_adm.const import END_SYSINFO_NET

    await setup_integration(hass, entry)
    adm.failing_paths.add(END_SYSINFO_NET.path)
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(IP_ADDRESS).state == "unavailable"
    assert hass.states.get("sensor.asustor_nas_adm_active_sessions").state == "1"


async def test_network_info_parsing() -> None:
    """Разбор ответов net и wan не зависит от структуры списка интерфейсов."""
    from custom_components.asustor_adm.parse import parse_network_info, parse_wan_ip

    network = parse_network_info(load_fixture("sysinfo_net"))
    assert network.ipv4 == "192.168.77.5"
    assert network.gateway == "192.168.77.1"
    assert network.dns == ("192.168.77.3", "77.88.8.8")

    assert parse_wan_ip(load_fixture("sysinfo_wan")) == "203.0.113.10"
    assert parse_wan_ip({"success": True}) is None
