"""Циклы опроса и изоляция сбоев (задачи 4.1, 4.2)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration

from custom_components.asustor_adm.const import (
    END_ACTIVITY,
    END_DISK_LIST,
    END_SYSINFO,
    END_VOLUME_LIST,
    SERVICE_ENDPOINTS,
    SLOW_CYCLE_STATIC_ENDPOINTS,
)

FAST_PATHS = (
    END_ACTIVITY.path,
    END_SYSINFO.path,
    END_VOLUME_LIST.path,
    END_DISK_LIST.path,
)


async def test_cycle_request_counts(hass, adm, entry) -> None:
    """Быстрый цикл делает четыре запроса, медленный — по числу эндпоинтов."""
    await setup_integration(hass, entry)
    runtime = entry.runtime_data

    assert runtime.fast.last_cycle_requests == 4
    expected_slow = (
        len(SERVICE_ENDPOINTS)
        + len(SLOW_CYCLE_STATIC_ENDPOINTS)
        + len(runtime.fast.volume_ids)
    )
    assert runtime.slow.last_cycle_requests == expected_slow


async def test_device_info_is_filled(hass, adm, entry) -> None:
    """Сведения об устройстве содержат модель, серийный номер, ADM и BIOS."""
    from homeassistant.helpers import device_registry as dr

    await setup_integration(hass, entry)
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier(
        ("asustor_adm", "SN012345678"), entry.entry_id
    )

    assert device is not None
    assert device.manufacturer == "ASUSTOR"
    assert device.model == "AS3304T"
    assert device.serial_number == "SN012345678"
    assert device.sw_version == "5.1.4.RM62"
    assert device.hw_version == "1.14"


async def test_device_info_version_is_updated(hass, adm, entry) -> None:
    """После обновления прошивки версия обновляется без пересоздания записи."""
    from homeassistant.helpers import device_registry as dr

    await setup_integration(hass, entry)
    adm.set_route(END_SYSINFO, load_fixture("sysinfo_new_version"))
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        ("asustor_adm", "SN012345678"), entry.entry_id
    )
    assert device.sw_version == "5.1.5.RN11"


async def test_slow_cycle_failure_is_isolated(hass, adm, entry) -> None:
    """Сбой запроса сервиса не мешает быстрым метрикам и остальным данным."""
    await setup_integration(hass, entry)
    runtime = entry.runtime_data
    smb_path = next(
        endpoint.path
        for endpoint in SERVICE_ENDPOINTS
        if endpoint.name == "windows.cgi"
    )

    adm.failing_paths.add(smb_path)
    await runtime.slow.async_refresh()
    await hass.async_block_till_done()

    assert runtime.slow.last_update_success is True
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage").state == "3.8"
    assert hass.states.get("sensor.asustor_nas_adm_active_sessions").state == "1"
    assert hass.states.get("binary_sensor.asustor_nas_adm_smb_service").state == (
        "unavailable"
    )
    assert hass.states.get("binary_sensor.asustor_nas_adm_nfs_service").state == "on"


async def test_all_fast_requests_failing_makes_entities_unavailable(
    hass, adm, entry
) -> None:
    """Полный отказ запросов переводит сущности в недоступность."""
    await setup_integration(hass, entry)
    adm.failing_paths.update(FAST_PATHS)

    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.fast.last_update_success is False
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage").state == "unavailable"


async def test_partial_failure_keeps_other_metrics(hass, adm, entry) -> None:
    """Отказ одного запроса цикла не отбрасывает остальные метрики."""
    await setup_integration(hass, entry)
    adm.set_route(END_SYSINFO, load_fixture("sysinfo_two_fans"))
    adm.failing_paths.add(END_SYSINFO.path)

    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.fast.last_update_success is True
    assert hass.states.get("sensor.asustor_nas_adm_cpu_usage").state == "3.8"
    assert hass.states.get("sensor.asustor_nas_adm_cpu_temperature").state == (
        "unavailable"
    )
