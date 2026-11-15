"""Двоичные сенсоры интеграции ASUSTOR ADM."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SERVICE_KEYS
from .entity import ADMFastEntity, ADMRuntime, ADMSlowEntity, DynamicEntityManager
from .models import ExternalDisk, FastData, SlowData
from .sensor import _disk_key, _disk_label

_SERVICE_ICONS = {
    "smb": "mdi:folder-network",
    "nfs": "mdi:server-network",
    "ftp": "mdi:folder-swap",
    "webdav": "mdi:cloud-outline",
    "ssh": "mdi:console",
    "sftp": "mdi:file-transfer",
    "rsync": "mdi:sync",
    "snmp": "mdi:monitor-eye",
    "tftp": "mdi:upload-network",
}


class ADMVolumeProblemSensor(ADMFastEntity, BinarySensorEntity):
    """Признак проблемы тома."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "volume_problem"

    def __init__(self, runtime: ADMRuntime, vid: int) -> None:
        """Создать признак проблемы для тома."""
        super().__init__(runtime, f"volume_{vid}_problem")
        self._vid = vid
        self._attr_translation_placeholders = {"volume": str(vid)}

    @property
    def available(self) -> bool:
        """Быть недоступным, если том исчез из ответа ADM."""
        return (
            super().available and self._runtime.fast_data.volume(self._vid) is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Сообщить о проблеме, если состояние тома не исправное."""
        volume = self._runtime.fast_data.volume(self._vid)
        if volume is None:
            return None
        healthy = volume.healthy
        return None if healthy is None else not healthy

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть состояние тома и сведения RAID."""
        volume = self._runtime.fast_data.volume(self._vid)
        if volume is None:
            return None
        attributes: dict[str, Any] = {}
        if volume.state is not None:
            attributes["state"] = volume.state
        if volume.fstype is not None:
            attributes["filesystem"] = volume.fstype
        attributes.update(volume.raid_attributes)
        details = self._runtime.slow_data.volumes.get(self._vid)
        if details is not None:
            attributes.update(details.raid_attributes)
        return attributes or None


class ADMDiskProblemSensor(ADMFastEntity, BinarySensorEntity):
    """Признак проблемы диска: состояние, SMART и ошибки."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "disk_problem"

    def __init__(self, runtime: ADMRuntime, did: int, slot: int | None) -> None:
        """Создать признак проблемы для диска."""
        super().__init__(runtime, f"{_disk_key(did, slot)}_problem")
        self._did = did
        self._attr_translation_placeholders = {"disk": _disk_label(did, slot)}

    @property
    def available(self) -> bool:
        """Быть недоступным, если диск исчез из ответа ADM."""
        return super().available and self._runtime.fast_data.disk(self._did) is not None

    @property
    def is_on(self) -> bool | None:
        """Сообщить о проблеме, если диск не исправен."""
        disk = self._runtime.fast_data.disk(self._did)
        if disk is None:
            return None
        healthy = disk.healthy
        return None if healthy is None else not healthy

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть сведения о диске."""
        disk = self._runtime.fast_data.disk(self._did)
        if disk is None:
            return None
        attributes = dict(disk.details)
        if disk.state is not None:
            attributes["state"] = disk.state
        if disk.smart_status is not None:
            attributes["smart_status"] = disk.smart_status
        return attributes or None


class ADMServiceBinarySensor(ADMSlowEntity, BinarySensorEntity):
    """Признак включения сетевого сервиса NAS."""

    def __init__(self, runtime: ADMRuntime, service: str) -> None:
        """Создать признак для одного сервиса."""
        super().__init__(runtime, f"service_{service}")
        self._service = service
        self._attr_translation_key = f"service_{service}"
        self._attr_icon = _SERVICE_ICONS.get(service)

    @property
    def is_on(self) -> bool | None:
        """Вернуть состояние сервиса из медленного цикла."""
        return self._runtime.slow_data.services.get(self._service)

    @property
    def available(self) -> bool:
        """Быть недоступным, если сервис не попал в ответ ADM."""
        return super().available and self.is_on is not None


class ADMUpdateAvailableSensor(ADMSlowEntity, BinarySensorEntity):
    """Признак доступности обновления прошивки ADM."""

    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_translation_key = "adm_update_available"

    def __init__(self, runtime: ADMRuntime) -> None:
        """Создать признак доступного обновления ADM."""
        super().__init__(runtime, "adm_update_available")

    @property
    def is_on(self) -> bool | None:
        """Вернуть подтверждённую доступность обновления.

        Значение вычисляется сверкой версий, поэтому ``None`` означает
        «неизвестно», а не «обновлений нет».
        """
        return self._runtime.slow_data.firmware.update_available

    @property
    def available(self) -> bool:
        """Быть недоступным, пока обновление не подтверждено версией."""
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть версии прошивки и сведения последней проверки ADM."""
        firmware = self._runtime.slow_data.firmware
        attributes: dict[str, Any] = {}
        if firmware.installed_version is not None:
            attributes["installed_version"] = firmware.installed_version
        if firmware.target_version is not None:
            attributes["target_version"] = firmware.target_version
        if firmware.notification_flag is not None:
            attributes["notification_flag"] = firmware.notification_flag
        if firmware.last_check_time is not None:
            attributes["last_check_time"] = firmware.last_check_time
        if firmware.last_check_error is not None:
            attributes["last_check_error"] = firmware.last_check_error
        return attributes or None


class ADMExternalDiskBinarySensor(ADMSlowEntity, BinarySensorEntity):
    """Признак наличия или готовности внешнего диска."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, runtime: ADMRuntime, alias: str, kind: str) -> None:
        """Создать признак для внешнего диска."""
        super().__init__(runtime, f"extdisk_{alias}_{kind}")
        self._alias = alias
        self._kind = kind
        self._attr_translation_key = (
            "external_disk_present" if kind == "present" else "external_disk_ready"
        )
        self._attr_translation_placeholders = {"disk": alias}
        if kind != "present":
            self._attr_device_class = None

    def _external(self) -> ExternalDisk | None:
        """Найти внешний диск по псевдониму."""
        for disk in self._runtime.slow_data.external_disks:
            if disk.alias == self._alias:
                return disk
        return None

    @property
    def available(self) -> bool:
        """Быть недоступным, если диск отключён."""
        return super().available and self._external() is not None

    @property
    def is_on(self) -> bool | None:
        """Вернуть наличие или готовность диска."""
        disk = self._external()
        if disk is None:
            return None
        if self._kind == "present":
            return True
        return disk.ready

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть сведения о внешнем диске."""
        disk = self._external()
        if disk is None:
            return None
        attributes = dict(disk.details)
        if disk.status is not None:
            attributes["status"] = disk.status
        return attributes or None


def _volume_keys(data: FastData) -> list[str]:
    """Ключи признаков проблем томов."""
    return [f"volume_{volume.vid}_problem" for volume in data.volumes]


def _disk_keys(data: FastData) -> list[str]:
    """Ключи признаков проблем дисков."""
    return [f"{_disk_key(disk.did, disk.slot)}_problem" for disk in data.disks]


def _service_keys(data: SlowData) -> list[str]:
    """Ключи признаков сервисов, о которых ADM сообщил сведения."""
    return [
        f"service_{key}" for key in SERVICE_KEYS if data.services.get(key) is not None
    ]


def _external_keys(data: SlowData) -> list[str]:
    """Ключи признаков наличия и готовности внешних дисков."""
    keys: list[str] = []
    for disk in data.external_disks:
        keys.extend((f"extdisk_{disk.alias}_present", f"extdisk_{disk.alias}_ready"))
    return keys


def _build_entity(runtime: ADMRuntime, key: str) -> BinarySensorEntity:
    """Создать сущность по ключу динамического объекта."""
    if key.startswith("volume_"):
        return ADMVolumeProblemSensor(runtime, int(key.split("_")[1]))
    if key.startswith("service_"):
        return ADMServiceBinarySensor(runtime, key.removeprefix("service_"))
    for suffix in ("present", "ready"):
        if key.endswith(f"_{suffix}"):
            alias = key[len("extdisk_") : -(len(suffix) + 1)]
            return ADMExternalDiskBinarySensor(runtime, alias, suffix)
    did, slot = _disk_identity(runtime, key)
    return ADMDiskProblemSensor(runtime, did, slot)


def _disk_identity(runtime: ADMRuntime, key: str) -> tuple[int, int | None]:
    """Найти идентификатор и отсек диска по ключу."""
    suffix = key.removesuffix("_problem")
    for disk in runtime.fast_data.disks:
        if _disk_key(disk.did, disk.slot) == suffix:
            return disk.did, disk.slot
    raise KeyError(key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать двоичные сенсоры записи."""
    runtime: ADMRuntime = entry.runtime_data
    async_add_entities([ADMUpdateAvailableSensor(runtime)])

    fast_manager: DynamicEntityManager[BinarySensorEntity] = DynamicEntityManager(
        async_add_entities,
        lambda keys: [_build_entity(runtime, key) for key in keys],
    )
    slow_manager: DynamicEntityManager[BinarySensorEntity] = DynamicEntityManager(
        async_add_entities,
        lambda keys: [_build_entity(runtime, key) for key in keys],
    )

    fast_manager.sync(_volume_keys(runtime.fast_data) + _disk_keys(runtime.fast_data))
    slow_manager.sync(
        _service_keys(runtime.slow_data) + _external_keys(runtime.slow_data)
    )

    entry.async_on_unload(
        runtime.fast.async_add_listener(
            lambda: fast_manager.sync(
                _volume_keys(runtime.fast_data) + _disk_keys(runtime.fast_data)
            )
        )
    )
    entry.async_on_unload(
        runtime.slow.async_add_listener(
            lambda: slow_manager.sync(
                _service_keys(runtime.slow_data) + _external_keys(runtime.slow_data)
            )
        )
    )
