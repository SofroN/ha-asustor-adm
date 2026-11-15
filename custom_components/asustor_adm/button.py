"""Кнопки управления питанием NAS ASUSTOR."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import POWER_RESTART, POWER_SHUTDOWN, POWER_SUSPEND
from .entity import ADMFastEntity, ADMRuntime
from .exceptions import ADMPowerError

_LOGGER = logging.getLogger(__name__)

#: Действия, после которых NAS перестаёт отвечать и сущности становятся недоступными.
_UNREACHABLE_ACTIONS = frozenset({POWER_SHUTDOWN, POWER_RESTART, POWER_SUSPEND})


class ADMPowerButton(ADMFastEntity, ButtonEntity):
    """Кнопка команды питания с защитой от автоматических повторов."""

    def __init__(self, runtime: ADMRuntime, action: str) -> None:
        """Создать кнопку для одного действия питания."""
        super().__init__(runtime, f"power_{action}")
        self._action = action
        self._attr_translation_key = action

    async def async_press(self) -> None:
        """Отправить команду питания по явному действию пользователя."""
        try:
            await self._runtime.client.async_power(self._action)
        except ADMPowerError as err:
            raise HomeAssistantError(
                translation_domain="asustor_adm",
                translation_key="power_failed",
                translation_placeholders={"action": self._action},
            ) from err
        if self._action in _UNREACHABLE_ACTIONS:
            self._runtime.fast.mark_device_unavailable()
            self._runtime.slow.mark_device_unavailable()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать кнопки питания по возможностям устройства и правам учётной записи."""
    runtime: ADMRuntime = entry.runtime_data
    entities: list[ButtonEntity] = []
    if runtime.is_admin:
        entities.append(ADMPowerButton(runtime, POWER_SHUTDOWN))
        entities.append(ADMPowerButton(runtime, POWER_RESTART))
    if runtime.can_suspend:
        entities.append(ADMPowerButton(runtime, POWER_SUSPEND))
    async_add_entities(entities)
