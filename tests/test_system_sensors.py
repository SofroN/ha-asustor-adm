"""Сенсоры ресурсов системы (задачи 5.1-5.3)."""

from __future__ import annotations

from helpers import load_fixture, setup_integration
from homeassistant.helpers import entity_registry as er

from custom_components.asustor_adm.const import END_ACTIVITY

CPU_USAGE = "sensor.asustor_nas_adm_cpu_usage"
MEMORY_USED = "sensor.asustor_nas_adm_memory_used"
MEMORY_PERCENT = "sensor.asustor_nas_adm_memory_utilization"


async def test_cpu_cores_and_total(hass, adm, entry) -> None:
    """Загрузка по ядрам и средняя загрузка публикуются отдельно."""
    await setup_integration(hass, entry)

    assert hass.states.get(CPU_USAGE).state == "3.8"
    for index, expected in ((1, "4.0"), (2, "3.0"), (3, "5.0"), (4, "3.0")):
        state = hass.states.get(f"sensor.asustor_nas_adm_cpu_core_{index}_usage")
        assert state.state == expected
        assert state.attributes["unit_of_measurement"] == "%"


async def test_core_count_change_removes_stale_entities(hass, adm, entry) -> None:
    """При уменьшении числа ядер сущности лишних ядер удаляются."""
    await setup_integration(hass, entry)
    registry = er.async_get(hass)

    adm.set_route(END_ACTIVITY, load_fixture("activity_two_cores"))
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.asustor_nas_adm_cpu_core_1_usage").state == "10.0"
    assert hass.states.get("sensor.asustor_nas_adm_cpu_core_2_usage").state == "20.0"
    assert hass.states.get("sensor.asustor_nas_adm_cpu_core_3_usage") is None
    assert (
        registry.async_get_entity_id("sensor", "asustor_adm", "SN012345678_core_3")
        is None
    )
    assert hass.states.get(CPU_USAGE).state == "15.0"


async def test_load_averages_strip_trailing_newline(hass, adm, entry) -> None:
    """Значение нагрузки с переводом строки даёт корректное число."""
    await setup_integration(hass, entry)

    assert hass.states.get("sensor.asustor_nas_adm_load_average_1_min").state == "2.28"
    assert hass.states.get("sensor.asustor_nas_adm_load_average_15_min").state == "2.22"


async def test_memory_volume_and_share(hass, adm, entry) -> None:
    """Память публикуется в МиБ и в процентах."""
    await setup_integration(hass, entry)

    used = hass.states.get(MEMORY_USED)
    assert used.state == "677.0"
    assert used.attributes["unit_of_measurement"] == "MiB"
    assert used.attributes["device_class"] == "data_size"
    assert hass.states.get(MEMORY_PERCENT).state == "34.9"


async def test_temperature_fans_and_uptime(hass, adm, entry) -> None:
    """Температура, кулеры и время работы публикуются из sysinfo."""
    await setup_integration(hass, entry)

    temperature = hass.states.get("sensor.asustor_nas_adm_cpu_temperature")
    assert temperature.state == "58.0"
    assert temperature.attributes["unit_of_measurement"] == "°C"

    fan = hass.states.get("sensor.asustor_nas_adm_fan_1_speed")
    assert fan.state == "776.0"
    assert fan.attributes["unit_of_measurement"] == "rpm"

    assert hass.states.get("sensor.asustor_nas_adm_uptime").state == "1672376"


async def test_missing_field_makes_only_related_entity_unknown(
    hass, adm, entry
) -> None:
    """Пропавшее поле делает недоступной только связанную сущность."""
    await setup_integration(hass, entry)

    payload = load_fixture("activity")
    payload.pop("avgload5")
    adm.set_route(END_ACTIVITY, payload)
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.asustor_nas_adm_load_average_5_min").state == (
        "unavailable"
    )
    assert hass.states.get(CPU_USAGE).state == "3.8"


async def test_foreign_structure_keeps_entities_available(hass, adm, entry) -> None:
    """Неизвестная структура ответа не валит цикл опроса."""
    await setup_integration(hass, entry)

    adm.set_route(END_ACTIVITY, load_fixture("activity_foreign_structure"))
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.fast.last_update_success is True
    assert hass.states.get(CPU_USAGE).state == "unavailable"
    assert hass.states.get("sensor.asustor_nas_adm_cpu_temperature").state == "58.0"
