"""Сущность обновления прошивки ADM."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ADMRuntime, ADMSlowEntity


class ADMFirmwareUpdateEntity(ADMSlowEntity, UpdateEntity):
    """Обновление прошивки ADM с известной целевой версией."""

    _attr_translation_key = "firmware"
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, runtime: ADMRuntime) -> None:
        """Создать сущность обновления прошивки."""
        super().__init__(runtime, "firmware_update")

    @property
    def installed_version(self) -> str | None:
        """Вернуть установленную версию ADM."""
        return self._runtime.slow_data.firmware.installed_version

    @property
    def latest_version(self) -> str | None:
        """Вернуть подтверждённую целевую версию ADM."""
        return self._runtime.slow_data.firmware.target_version

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Отказать в установке: команда установки на NAS не отправляется."""
        raise HomeAssistantError(
            translation_domain="asustor_adm",
            translation_key="install_not_supported",
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать сущность обновления только при известной целевой версии."""
    runtime: ADMRuntime = entry.runtime_data
    known: set[str] = set()

    def _sync() -> None:
        target = runtime.slow_data.firmware.target_version
        if target is None or target in known:
            return
        known.add(target)
        async_add_entities([ADMFirmwareUpdateEntity(runtime)])

    _sync()
    entry.async_on_unload(runtime.slow.async_add_listener(_sync))
