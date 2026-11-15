"""Статусы сетевых сервисов и сессии (задача 7.2)."""

from __future__ import annotations

import pytest
from helpers import load_fixture, setup_integration

from custom_components.asustor_adm.const import SERVICE_DEFINITIONS, SERVICE_KEYS

EXPECTED = {
    "smb": "on",
    "nfs": "on",
    "ftp": "on",
    "webdav": "on",
    "ssh": "off",
    "sftp": "off",
    "rsync": "on",
    "snmp": "on",
    "tftp": "off",
}


@pytest.mark.parametrize(("service", "expected"), sorted(EXPECTED.items()))
async def test_service_state(hass, adm, entry, service: str, expected: str) -> None:
    """Каждый из девяти сервисов публикует своё состояние."""
    await setup_integration(hass, entry)
    state = hass.states.get(f"binary_sensor.asustor_nas_adm_{service}_service")

    assert state is not None
    assert state.state == expected


async def test_ssh_and_sftp_are_independent(hass, adm, entry) -> None:
    """SSH и SFTP публикуются как два независимых признака."""
    terminal = next(
        definition.endpoint
        for definition in SERVICE_DEFINITIONS
        if definition.key == "ssh"
    )
    adm.set_route(terminal, load_fixture("service_terminal_ssh_only"))
    await setup_integration(hass, entry)

    assert hass.states.get("binary_sensor.asustor_nas_adm_ssh_service").state == "on"
    assert hass.states.get("binary_sensor.asustor_nas_adm_sftp_service") is None


async def test_service_without_data_is_not_created(hass, adm, entry) -> None:
    """Сервис, сведений о котором нет, не создаёт сущность."""
    terminal = next(
        definition.endpoint
        for definition in SERVICE_DEFINITIONS
        if definition.key == "ssh"
    )
    adm.set_route(terminal, {"success": True})
    await setup_integration(hass, entry)

    assert hass.states.get("binary_sensor.asustor_nas_adm_ssh_service") is None
    assert hass.states.get("binary_sensor.asustor_nas_adm_smb_service").state == "on"
    assert set(SERVICE_KEYS) == set(EXPECTED)


async def test_sessions_count(hass, adm, entry) -> None:
    """Число активных сессий публикуется в медленном цикле."""
    await setup_integration(hass, entry)
    assert hass.states.get("sensor.asustor_nas_adm_active_sessions").state == "1"


async def test_sessions_zero_stays_available(hass, adm, entry) -> None:
    """Отсутствие сессий даёт ноль и не делает сущность недоступной."""
    from custom_components.asustor_adm.const import END_SESSIONS

    adm.set_route(END_SESSIONS, load_fixture("sessions_empty"))
    await setup_integration(hass, entry)

    state = hass.states.get("sensor.asustor_nas_adm_active_sessions")
    assert state.state == "0"
    assert state.state != "unavailable"
