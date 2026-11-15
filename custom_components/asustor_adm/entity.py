"""Базовые сущности и общие сведения об устройстве."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ADMClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_USE_SSL,
    DEFAULT_PORT,
    DEFAULT_USE_SSL,
    DEVICE_NAME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import ADMFastCoordinator, ADMSlowCoordinator
from .models import FastData, SlowData, SysInfo


@dataclass(slots=True)
class ADMRuntime:
    """Общие объекты записи интеграции."""

    entry: ConfigEntry
    client: ADMClient
    fast: ADMFastCoordinator
    slow: ADMSlowCoordinator
    identifier: str

    @property
    def fast_data(self) -> FastData:
        """Вернуть последние данные быстрого цикла или пустую структуру."""
        return self.fast.data or FastData()

    @property
    def slow_data(self) -> SlowData:
        """Вернуть последние данные медленного цикла или пустую структуру."""
        return self.slow.data or SlowData()

    @property
    def system(self) -> SysInfo:
        """Вернуть сведения об устройстве из последнего опроса."""
        return self.fast_data.system

    @property
    def is_admin(self) -> bool:
        """Вернуть признак прав администратора из ответа авторизации."""
        login = self.client.login
        return bool(login and login.is_admin)

    @property
    def can_suspend(self) -> bool:
        """Вернуть признак поддержки перехода в сон."""
        login = self.client.login
        return bool(login and login.can_suspend)

    def unique_id(self, suffix: str) -> str:
        """Построить стабильный уникальный идентификатор сущности."""
        return f"{self.identifier}_{suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        """Собрать сведения об устройстве для реестра."""
        system = self.system
        host = self.entry.data[CONF_HOST]
        port = self.entry.data.get(CONF_PORT, DEFAULT_PORT)
        scheme = (
            "https" if self.entry.data.get(CONF_USE_SSL, DEFAULT_USE_SSL) else "http"
        )
        info = DeviceInfo(
            identifiers={(DOMAIN, self.identifier)},
            name=DEVICE_NAME,
            manufacturer=MANUFACTURER,
            configuration_url=f"{scheme}://{host}:{port}/portal/",
        )
        if system.model is not None:
            info["model"] = system.model
        if system.serial is not None:
            info["serial_number"] = system.serial
        if system.adm_version is not None:
            info["sw_version"] = system.adm_version
        if system.bios is not None:
            info["hw_version"] = system.bios
        return info


class ADMFastEntity(CoordinatorEntity[ADMFastCoordinator]):
    """Сущность, обновляемая в быстром цикле опроса."""

    _attr_has_entity_name = True

    def __init__(self, runtime: ADMRuntime, unique_suffix: str) -> None:
        """Создать сущность с уникальным идентификатором устройства."""
        super().__init__(runtime.fast)
        self._runtime = runtime
        self._attr_unique_id = runtime.unique_id(unique_suffix)

    @property
    def device_info(self) -> DeviceInfo:
        """Вернуть сведения об устройстве."""
        return self._runtime.device_info


class ADMSlowEntity(CoordinatorEntity[ADMSlowCoordinator]):
    """Сущность, обновляемая в медленном цикле опроса."""

    _attr_has_entity_name = True

    def __init__(self, runtime: ADMRuntime, unique_suffix: str) -> None:
        """Создать сущность с уникальным идентификатором устройства."""
        super().__init__(runtime.slow)
        self._runtime = runtime
        self._attr_unique_id = runtime.unique_id(unique_suffix)

    @property
    def device_info(self) -> DeviceInfo:
        """Вернуть сведения об устройстве."""
        return self._runtime.device_info


_EntityT = TypeVar("_EntityT", bound=Entity)


class DynamicEntityManager(Generic[_EntityT]):
    """Добавляет сущности, когда в ответах ADM появляются новые объекты."""

    def __init__(
        self,
        async_add_entities: Callable[[list[_EntityT]], None],
        factory: Callable[[list[str]], Iterable[_EntityT]],
    ) -> None:
        """Сохранить способ создания сущностей для новых ключей."""
        self._async_add_entities = async_add_entities
        self._factory = factory
        self._known: set[str] = set()

    @callback
    def sync(self, keys: Iterable[str]) -> None:
        """Создать сущности для ключей, которых ещё не было."""
        new_keys = [key for key in keys if key not in self._known]
        if not new_keys:
            return
        self._known.update(new_keys)
        self._async_add_entities(list(self._factory(new_keys)))

    @callback
    def discard(self, key: str) -> None:
        """Забыть ключ, чтобы сущность можно было создать снова."""
        self._known.discard(key)

    @property
    def known(self) -> frozenset[str]:
        """Вернуть ключи, для которых сущности уже созданы."""
        return frozenset(self._known)
