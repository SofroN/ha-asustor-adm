"""Признаки проблем томов и дисков (задача 7.1)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration

from custom_components.asustor_adm.const import END_DISK_LIST, END_VOLUME_LIST

PROBLEM_1 = "binary_sensor.asustor_nas_adm_volume_1_problem"
DISK_1 = "binary_sensor.asustor_nas_adm_disk_1_problem"
DISK_2 = "binary_sensor.asustor_nas_adm_disk_2_problem"


async def test_healthy_storage_has_no_problems(hass, adm, entry) -> None:
    """Исправные тома и диски не сообщают о проблемах."""
    await setup_integration(hass, entry)

    assert hass.states.get(PROBLEM_1).state == "off"
    assert hass.states.get(DISK_1).state == "off"
    assert hass.states.get(DISK_1).attributes["device_class"] == "problem"
    assert hass.states.get(DISK_1).attributes["smart_status"] == "Healthy"


async def test_degraded_array_reports_problem(hass, adm, entry) -> None:
    """Деградация RAID переводит признак в состояние проблемы."""
    adm.set_route(END_VOLUME_LIST, load_fixture("volumes_degraded"))
    await setup_integration(hass, entry)

    assert hass.states.get("binary_sensor.asustor_nas_adm_volume_2_problem").state == (
        "on"
    )


async def test_smart_warning_reports_problem(hass, adm, entry) -> None:
    """Предупреждение SMART делает диск проблемным."""
    adm.set_route(END_DISK_LIST, load_fixture("disks_smart_warning"))
    await setup_integration(hass, entry)

    assert hass.states.get(DISK_1).state == "off"
    assert hass.states.get(DISK_2).state == "on"
    assert hass.states.get(DISK_2).attributes["smart_status"] == "Warning"
