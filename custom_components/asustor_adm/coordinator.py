"""Координаторы опроса ADM: быстрый и медленный циклы."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ADMClient
from .const import (
    DOMAIN,
    END_ACTIVITY,
    END_APP_UPDATES,
    END_DISK_LIST,
    END_EXT_DISK,
    END_FIRMWARE,
    END_SESSIONS,
    END_SYSINFO,
    END_SYSINFO_NET,
    END_SYSINFO_WAN,
    END_TASKS,
    END_VOLUME_GET,
    END_VOLUME_LIST,
    SERVICE_DEFINITIONS,
    SERVICE_ENDPOINTS,
)
from .exceptions import ADMAuthError, ADMConnectionError, ADMError, ADMResponseError
from .models import (
    Activity,
    FastData,
    FirmwareInfo,
    NetworkInfo,
    SlowData,
    SysInfo,
    Volume,
)
from .parse import (
    parse_activity,
    parse_app_updates,
    parse_disks,
    parse_external_disks,
    parse_firmware,
    parse_network_info,
    parse_service_state,
    parse_sessions,
    parse_sysinfo,
    parse_tasks,
    parse_volume_details,
    parse_volumes,
    parse_wan_ip,
)
from .values import version_is_newer

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

#: Префикс ошибок соединения для журнала — без адреса и параметров запроса.
_POWER_REASON = "NAS недоступен после команды управления питанием"


class ADMBaseCoordinator(DataUpdateCoordinator[_T]):
    """Общая часть координаторов: сессия, счётчик запросов, ошибки."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
        client: ADMClient,
        name: str,
        interval: int,
    ) -> None:
        """Создать координатор с общим клиентом ADM."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {name}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.client = client
        self.last_cycle_requests: int = 0
        self._cycle_requests: int = 0
        self._volume_ids: tuple[int, ...] = ()
        self._last_firmware = FirmwareInfo()
        self._cycle_errors: dict[str, Exception] = {}

    async def _request(self, endpoint: Any, **kwargs: Any) -> dict[str, Any]:
        """Выполнить запрос, посчитав его для проверки состава цикла."""
        self._cycle_requests += 1
        try:
            return await self.client.async_request(endpoint, **kwargs)
        except ADMAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

    def _reset_counter(self) -> None:
        """Сбросить счётчик запросов и ошибок перед новым циклом."""
        self._cycle_requests = 0
        self._cycle_errors.clear()

    def _commit_counter(self) -> None:
        """Зафиксировать число запросов завершённого цикла."""
        self.last_cycle_requests = self._cycle_requests

    @property
    def cycle_errors(self) -> dict[str, str]:
        """Вернуть пути запросов последнего цикла, завершившихся ошибкой."""
        return {
            path: type(error).__name__ for path, error in self._cycle_errors.items()
        }

    def mark_device_unavailable(self, reason: str = _POWER_REASON) -> None:
        """Пометить сущности недоступными без повторных запросов к NAS."""
        self.async_set_update_error(UpdateFailed(reason))


class ADMFastCoordinator(ADMBaseCoordinator[FastData]):
    """Быстрый цикл: ресурсы процессора, память, сеть, тома, диски."""

    async def _async_update_data(self) -> FastData:
        """Опросить четыре эндпоинта быстрого цикла, ухудшая данные по частям."""
        self._reset_counter()
        failures = 0
        try:
            activity_payload = await self._request(END_ACTIVITY)
        except (ADMConnectionError, ADMError) as err:
            _LOGGER.debug("activity request failed: %s", err)
            self._cycle_errors[END_ACTIVITY.path] = err
            activity_payload = None
            failures += 1
        try:
            system_payload = await self._request(END_SYSINFO)
        except (ADMConnectionError, ADMError) as err:
            _LOGGER.debug("sysinfo request failed: %s", err)
            self._cycle_errors[END_SYSINFO.path] = err
            system_payload = None
            failures += 1
        try:
            volumes_payload = await self._request(END_VOLUME_LIST)
        except (ADMConnectionError, ADMError) as err:
            _LOGGER.debug("volume list request failed: %s", err)
            self._cycle_errors[END_VOLUME_LIST.path] = err
            volumes_payload = None
            failures += 1
        try:
            disks_payload = await self._request(END_DISK_LIST)
        except (ADMConnectionError, ADMError) as err:
            _LOGGER.debug("disk list request failed: %s", err)
            self._cycle_errors[END_DISK_LIST.path] = err
            disks_payload = None
            failures += 1
        finally:
            self._commit_counter()

        if failures == self._cycle_requests:
            raise UpdateFailed("all fast cycle requests failed")

        activity = _safe_parse(parse_activity, activity_payload, Activity(), "activity")
        system = _safe_parse(parse_sysinfo, system_payload, SysInfo(), "sysinfo")
        volumes = _safe_parse(parse_volumes, volumes_payload, (), "volumes")
        disks = _safe_parse(parse_disks, disks_payload, (), "disks")
        self._volume_ids = tuple(volume.vid for volume in volumes)
        return FastData(system=system, activity=activity, volumes=volumes, disks=disks)

    @property
    def volume_ids(self) -> tuple[int, ...]:
        """Вернуть идентификаторы томов из последнего успешного опроса."""
        return self._volume_ids


class ADMSlowCoordinator(ADMBaseCoordinator[SlowData]):
    """Медленный цикл: сервисы, сессии, обновления, внешние диски, RAID."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
        client: ADMClient,
        name: str,
        interval: int,
        fast_coordinator: ADMFastCoordinator,
    ) -> None:
        """Создать медленный координатор, читающий тома быстрого цикла."""
        super().__init__(hass, entry=entry, client=client, name=name, interval=interval)
        self._fast = fast_coordinator

    async def _async_update_data(self) -> SlowData:
        """Опросить медленный цикл, ухудшая данные по частям."""
        self._reset_counter()
        failures = 0

        async def _fetch(endpoint: Any, params: Any = None) -> dict[str, Any] | None:
            """Выполнить запрос, вернув None при неудаче без прерывания цикла."""
            nonlocal failures
            try:
                return await self._request(endpoint, params=params)
            except (ADMConnectionError, ADMError) as err:
                _LOGGER.debug("%s request failed: %s", endpoint.path, err)
                self._cycle_errors[endpoint.path] = err
                failures += 1
                return None

        try:
            services = await self._async_fetch_services(_fetch)
            net_payload = await _fetch(END_SYSINFO_NET)
            wan_payload = await _fetch(END_SYSINFO_WAN)
            sessions_payload = await _fetch(END_SESSIONS)
            tasks_payload = await _fetch(END_TASKS)
            external_payload = await _fetch(END_EXT_DISK)
            accounts_payload = await _fetch(END_APP_UPDATES)
            volumes = await self._async_fetch_volume_details(_fetch)
            firmware_payload = await _fetch(END_FIRMWARE)
            firmware = self._async_fetch_firmware(firmware_payload)
        finally:
            self._commit_counter()

        if failures == self._cycle_requests:
            raise UpdateFailed("all slow cycle requests failed")

        return SlowData(
            services=services,
            sessions=_safe_parse(parse_sessions, sessions_payload, None, "sessions"),
            tasks=_safe_parse(parse_tasks, tasks_payload, None, "tasks"),
            firmware=firmware,
            network=_safe_parse(
                parse_network_info, net_payload, NetworkInfo(), "network"
            ),
            wan_ip=_safe_parse(parse_wan_ip, wan_payload, None, "wan_ip"),
            app_updates=_safe_parse(
                parse_app_updates, accounts_payload, None, "app_updates"
            ),
            external_disks=_safe_parse(
                parse_external_disks, external_payload, (), "external_disks"
            ),
            volumes=volumes,
        )

    async def _async_fetch_services(
        self, fetch: Callable[..., Awaitable[dict[str, Any] | None]]
    ) -> dict[str, bool | None]:
        """Собрать состояния сервисов: один запрос на уникальный эндпоинт."""
        payloads: dict[Any, dict[str, Any] | None] = {}
        for endpoint in SERVICE_ENDPOINTS:
            payloads[endpoint] = await fetch(endpoint)
        states: dict[str, bool | None] = {}
        for definition in SERVICE_DEFINITIONS:
            payload = payloads.get(definition.endpoint)
            if payload is None:
                states[definition.key] = None
                continue
            states[definition.key] = _safe_parse(
                lambda payload, definition=definition: parse_service_state(
                    payload, definition
                ),
                payload,
                None,
                f"service {definition.key}",
            )
        return states

    async def _async_fetch_volume_details(
        self, fetch: Callable[..., Awaitable[dict[str, Any] | None]]
    ) -> dict[int, Volume]:
        """Получить сведения RAID по каждому тому."""
        volumes: dict[int, Volume] = {}
        for vid in self._fast.volume_ids:
            payload = await fetch(END_VOLUME_GET, {"vid": vid})
            if payload is None:
                continue
            volume = _safe_parse(
                parse_volume_details, payload, None, f"volume {vid} details"
            )
            if volume is not None:
                volumes[vid] = volume
        return volumes

    def _async_fetch_firmware(self, payload: dict[str, Any] | None) -> FirmwareInfo:
        """Свести сведения о прошивке и вычислить признак доступного обновления."""
        if payload is None:
            error = self._cycle_errors.get(END_FIRMWARE.path)
            code = error.code if isinstance(error, ADMResponseError) else None
            _LOGGER.debug("Firmware check unavailable, code %s", code)
            return _carry_firmware(self._last_firmware, code)
        parsed = _safe_parse(parse_firmware, payload, None, "firmware")
        if parsed is None:
            return _carry_firmware(self._last_firmware, None)
        # Установленная версия описывает устройство и переживает ответ без неё.
        # Целевая версия, флаг и время проверки — только сведения этого ответа:
        # унаследованная целевая версия и была источником ложного обновления.
        installed = parsed.installed_version or self._last_firmware.installed_version
        firmware = FirmwareInfo(
            installed_version=installed,
            update_available=_firmware_update_available(
                installed, parsed.target_version
            ),
            target_version=parsed.target_version,
            notification_flag=parsed.notification_flag,
            last_check_time=parsed.last_check_time,
        )
        if firmware.notification_flag and firmware.target_version is None:
            _LOGGER.debug(
                "Update notification without target version: installed %s, "
                "notification flag %s",
                installed,
                firmware.notification_flag,
            )
        self._last_firmware = firmware
        return firmware


def _firmware_update_available(
    installed: str | None, target: str | None
) -> bool | None:
    """Вычислить признак обновления по сведённым версиям.

    Обновлением считается только подтверждённая более новая целевая версия;
    ``None`` означает «неизвестно»: цели нет либо версии не сравнимы.
    """
    if target is None:
        return None
    return version_is_newer(target, installed)


def _carry_firmware(previous: FirmwareInfo, error_code: int | None) -> FirmwareInfo:
    """Вернуть последнее подтверждённое состояние прошивки с отметкой о сбое."""
    return FirmwareInfo(
        installed_version=previous.installed_version,
        update_available=previous.update_available,
        target_version=previous.target_version,
        last_check_error=error_code,
        notification_flag=previous.notification_flag,
        last_check_time=previous.last_check_time,
    )


def _safe_parse(
    parser: Callable[[Mapping[str, Any] | None], _T],
    payload: Mapping[str, Any] | None,
    default: _T,
    what: str,
) -> _T:
    """Разобрать ответ, не прерывая цикл опроса при неожиданной структуре."""
    try:
        return parser(payload)
    except Exception:
        _LOGGER.warning("Failed to parse %s response, keeping empty value", what)
        return default


__all__ = ["ADMFastCoordinator", "ADMSlowCoordinator"]
