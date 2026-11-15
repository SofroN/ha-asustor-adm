"""Интеграция ASUSTOR NAS (ADM)."""

from __future__ import annotations

import logging
from typing import Final

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ADMClient
from .const import (
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SLOW_INTERVAL,
    CONF_USE_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SLOW_INTERVAL,
    DEFAULT_USE_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import ADMFastCoordinator, ADMSlowCoordinator
from .entity import ADMRuntime
from .exceptions import ADMAuthError, ADMConnectionError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настроить запись: авторизоваться и запустить оба цикла опроса."""
    data = entry.data
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    client = ADMClient(
        session,
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        account=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        use_ssl=data.get(CONF_USE_SSL, DEFAULT_USE_SSL),
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )

    try:
        await client.async_login()
        fast = ADMFastCoordinator(
            hass,
            entry=entry,
            client=client,
            name="fast",
            interval=int(entry.options.get(CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL)),
        )
        await fast.async_config_entry_first_refresh()
        slow = ADMSlowCoordinator(
            hass,
            entry=entry,
            client=client,
            name="slow",
            interval=int(entry.options.get(CONF_SLOW_INTERVAL, DEFAULT_SLOW_INTERVAL)),
            fast_coordinator=fast,
        )
        await slow.async_config_entry_first_refresh()
    except ADMAuthError as err:
        await session.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except ADMConnectionError as err:
        await session.close()
        raise ConfigEntryNotReady(str(err)) from err
    except (ConfigEntryAuthFailed, ConfigEntryNotReady):
        await session.close()
        raise

    serial = fast.data.system.serial if fast.data else None
    entry.runtime_data = ADMRuntime(
        entry=entry,
        client=client,
        fast=fast,
        slow=slow,
        identifier=serial or data[CONF_HOST],
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_sync_device_info(hass, entry)
    entry.async_on_unload(
        fast.async_add_listener(lambda: _async_sync_device_info(hass, entry))
    )
    return True


@callback
def _async_sync_device_info(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перенести изменившиеся версии и модель в реестр устройств."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier(
        (DOMAIN, runtime.identifier), entry.entry_id
    )
    if device is None:
        return
    system = runtime.system
    changes: dict[str, str] = {}
    for key, value, current in (
        ("sw_version", system.adm_version, device.sw_version),
        ("hw_version", system.bios, device.hw_version),
        ("model", system.model, device.model),
        ("serial_number", system.serial, device.serial_number),
    ):
        if value is not None and value != current:
            changes[key] = value
    if changes:
        registry.async_update_device(device.id, **changes)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузить платформы и закрыть сессию ADM."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезагрузить запись после изменения настроек опроса."""
    await hass.config_entries.async_reload(entry.entry_id)
