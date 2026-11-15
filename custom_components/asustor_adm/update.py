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
    """Обновление прошивки ADM с подтверждённой более новой версией."""

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
        """Вернуть версию, которую Home Assistant покажет как доступную.

        Целевая версия отдаётся только когда она подтверждённо новее
        установленной. Иначе возвращается установленная версия: сравнение
        равных строк даёт «обновлений нет», а устаревшая или несравнимая цель
        не может выглядеть обновлением.
        """
        firmware = self._runtime.slow_data.firmware
        if firmware.target_version is not None and firmware.update_available is True:
            return firmware.target_version
        return firmware.installed_version

    @property
    def available(self) -> bool:
        """Быть недоступной, пока ADM не сообщил целевую версию."""
        return (
            super().available
            and self._runtime.slow_data.firmware.target_version is not None
        )

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
    """Создать сущность обновления только при подтверждённой новой версии."""
    runtime: ADMRuntime = entry.runtime_data
    known: set[str] = set()

    def _sync() -> None:
        firmware = runtime.slow_data.firmware
        target = firmware.target_version
        if firmware.update_available is not True or target is None or target in known:
            return
        known.add(target)
        async_add_entities([ADMFirmwareUpdateEntity(runtime)])

    _sync()
    entry.async_on_unload(runtime.slow.async_add_listener(_sync))
