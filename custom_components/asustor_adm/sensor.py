"""Сенсоры интеграции ASUSTOR ADM."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    Platform,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, END_DISK_SMART
from .entity import ADMFastEntity, ADMRuntime, ADMSlowEntity, DynamicEntityManager
from .exceptions import ADMError
from .models import FastData, SlowData
from .parse import parse_smart
from .values import bytes_to_gib, kb_to_mib

_LOGGER = logging.getLogger(__name__)

_SPEED_UNIT = UnitOfDataRate.KILOBYTES_PER_SECOND
_SLOW_SMART_PARAMS = {"page": 1, "start": 0, "limit": 25}


@dataclass(frozen=True, kw_only=True)
class ADMFastSensorDescription(SensorEntityDescription):
    """Описание сенсора, значение которого берётся из быстрого цикла."""

    value_fn: Callable[[FastData], Any]


@dataclass(frozen=True, kw_only=True)
class ADMSlowSensorDescription(SensorEntityDescription):
    """Описание сенсора, значение которого берётся из медленного цикла."""

    value_fn: Callable[[SlowData], Any]
    attributes_fn: Callable[[SlowData], dict[str, Any] | None] | None = None


FAST_SENSORS: tuple[ADMFastSensorDescription, ...] = (
    ADMFastSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:cpu-64-bit",
        value_fn=lambda data: data.activity.cpu_total,
    ),
    ADMFastSensorDescription(
        key="load_1",
        translation_key="load_1",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:speedometer",
        value_fn=lambda data: data.activity.load_1,
    ),
    ADMFastSensorDescription(
        key="load_5",
        translation_key="load_5",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:speedometer",
        value_fn=lambda data: data.activity.load_5,
    ),
    ADMFastSensorDescription(
        key="load_15",
        translation_key="load_15",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:speedometer",
        value_fn=lambda data: data.activity.load_15,
    ),
    ADMFastSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: kb_to_mib(data.activity.memory_used_kb),
    ),
    ADMFastSensorDescription(
        key="memory_used_percent",
        translation_key="memory_used_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.activity.memory_used_percent,
    ),
    ADMFastSensorDescription(
        key="uptime",
        translation_key="uptime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        icon="mdi:clock-outline",
        value_fn=lambda data: (
            int(data.system.uptime) if data.system.uptime is not None else None
        ),
    ),
)

SLOW_SENSORS: tuple[ADMSlowSensorDescription, ...] = (
    ADMSlowSensorDescription(
        key="sessions",
        translation_key="sessions",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:account-multiple",
        value_fn=lambda data: data.sessions,
    ),
    ADMSlowSensorDescription(
        key="app_updates",
        translation_key="app_updates",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:package-up",
        value_fn=lambda data: data.app_updates,
    ),
    ADMSlowSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        icon="mdi:ip-network",
        value_fn=lambda data: data.network.ipv4,
        attributes_fn=lambda data: _network_attributes(data),
    ),
    ADMSlowSensorDescription(
        key="wan_ip",
        translation_key="wan_ip",
        icon="mdi:wan",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.wan_ip,
    ),
    ADMSlowSensorDescription(
        key="active_tasks",
        translation_key="active_tasks",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:progress-clock",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.tasks,
    ),
)


def _network_attributes(data: SlowData) -> dict[str, Any] | None:
    """Собрать сетевые сведения для атрибутов сенсора IP-адреса."""
    attributes: dict[str, Any] = {}
    network = data.network
    if network.ipv6 is not None:
        attributes["ipv6"] = network.ipv6
    if network.mac is not None:
        attributes["mac"] = network.mac
    if network.gateway is not None:
        attributes["gateway"] = network.gateway
    if network.dns:
        attributes["dns"] = list(network.dns)
    return attributes or None


def _disk_key(disk_id: int | None, slot: int | None) -> str:
    """Построить стабильный ключ диска по номеру отсека."""
    return f"disk_{slot if slot is not None else disk_id}"


def _disk_label(disk_id: int | None, slot: int | None) -> str:
    """Построить отображаемое имя диска."""
    return f"Disk {slot if slot is not None else disk_id}"


class ADMFastSensor(ADMFastEntity, SensorEntity):
    """Сенсор быстрого цикла с описанием."""

    entity_description: ADMFastSensorDescription

    def __init__(
        self,
        runtime: ADMRuntime,
        description: ADMFastSensorDescription,
        unique_suffix: str,
    ) -> None:
        """Создать сенсор по описанию."""
        super().__init__(runtime, unique_suffix)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> Any:
        """Вернуть значение из последнего опроса."""
        return self.entity_description.value_fn(self._runtime.fast_data)

    @property
    def available(self) -> bool:
        """Быть недоступным, если связанное поле отсутствует в ответе."""
        return super().available and self.native_value is not None


class ADMSlowSensor(ADMSlowEntity, SensorEntity):
    """Сенсор медленного цикла с описанием."""

    entity_description: ADMSlowSensorDescription

    def __init__(
        self,
        runtime: ADMRuntime,
        description: ADMSlowSensorDescription,
        unique_suffix: str,
    ) -> None:
        """Создать сенсор по описанию."""
        super().__init__(runtime, unique_suffix)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> Any:
        """Вернуть значение из последнего опроса."""
        return self.entity_description.value_fn(self._runtime.slow_data)

    @property
    def available(self) -> bool:
        """Быть недоступным, если связанное поле отсутствует в ответе."""
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть дополнительные сведения о сети."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self._runtime.slow_data)


class ADMDynamicSensor(ADMFastEntity, SensorEntity):
    """Сенсор объекта, появляющегося в ответах ADM динамически."""

    def __init__(
        self,
        runtime: ADMRuntime,
        *,
        unique_suffix: str,
        name_key: str,
        placeholders: dict[str, str | int],
        value_fn: Callable[[FastData], Any],
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
        precision: int | None = None,
        attributes_fn: Callable[[ADMRuntime], dict[str, Any] | None] | None = None,
        enabled_by_default: bool = True,
        also_listen_to: DataUpdateCoordinator[Any] | None = None,
    ) -> None:
        """Создать динамический сенсор с явными параметрами публикации."""
        super().__init__(runtime, unique_suffix)
        self._attr_translation_key = name_key
        self._attr_translation_placeholders = {
            key: str(value) for key, value in placeholders.items()
        }
        self._value_fn = value_fn
        self._attributes_fn = attributes_fn
        self._attr_entity_registry_enabled_default = enabled_by_default
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class
        if icon is not None:
            self._attr_icon = icon
        if precision is not None:
            self._attr_suggested_display_precision = precision
        if also_listen_to is not None:
            self.async_on_remove(
                also_listen_to.async_add_listener(self._handle_coordinator_update)
            )

    @property
    def native_value(self) -> Any:
        """Вернуть значение из последнего опроса."""
        return self._value_fn(self._runtime.fast_data)

    @property
    def available(self) -> bool:
        """Быть недоступным, если связанное поле отсутствует в ответе."""
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть дополнительные сведения об объекте."""
        if self._attributes_fn is None:
            return None
        return self._attributes_fn(self._runtime)


class ADMSmartSensor(ADMFastEntity, SensorEntity):
    """Атрибуты SMART диска, запрашиваемые по требованию."""

    _attr_translation_key = "disk_smart"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:harddisk-plus"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        runtime: ADMRuntime,
        *,
        disk_id: int,
        slot: int | None,
        placeholders: dict[str, str | int],
    ) -> None:
        """Создать сущность наработки и атрибутов SMART для диска."""
        super().__init__(runtime, f"{_disk_key(disk_id, slot)}_smart")
        self._attr_translation_placeholders = {
            key: str(value) for key, value in placeholders.items()
        }
        self._disk_id = disk_id
        self._smart: Any = None

    @property
    def should_poll(self) -> bool:
        """Разрешить ручное обновление через `homeassistant.update_entity`."""
        return True

    @property
    def native_value(self) -> Any:
        """Вернуть наработку в часах из последнего запроса атрибутов."""
        return self._smart.power_on_hours if self._smart is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть разобранные атрибуты SMART."""
        if self._smart is None:
            return None
        attributes: dict[str, Any] = dict(self._smart.attributes)
        for key, value in (
            ("reallocated_sectors", self._smart.reallocated_sectors),
            ("pending_sectors", self._smart.pending_sectors),
            ("temperature", self._smart.temperature),
        ):
            if value is not None:
                attributes[key] = value
        return attributes

    async def async_update(self) -> None:
        """Запросить атрибуты SMART при явном обновлении сущности."""
        try:
            payload = await self._runtime.client.async_request(
                END_DISK_SMART,
                params={"did": self._disk_id, **_SLOW_SMART_PARAMS},
            )
        except ADMError as err:
            _LOGGER.debug("SMART request for disk %s failed: %s", self._disk_id, err)
            return
        self._smart = parse_smart(payload)


def _volume_attributes(runtime: ADMRuntime, vid: int) -> dict[str, Any] | None:
    """Собрать атрибуты RAID тома из быстрого и медленного циклов."""
    attributes: dict[str, Any] = {}
    volume = runtime.fast_data.volume(vid)
    if volume is not None:
        attributes.update(volume.raid_attributes)
    details = runtime.slow_data.volumes.get(vid)
    if details is not None:
        attributes.update(details.raid_attributes)
    return attributes or None


def _disk_attributes(
    runtime: ADMRuntime, disk_id: int, slot: int | None
) -> dict[str, Any]:
    """Собрать сведения о диске для публикации в атрибутах."""
    for disk in runtime.fast_data.disks:
        if disk.did == disk_id:
            return disk.details
    return {"slot": slot} if slot is not None else {}


def _core_keys(data: FastData) -> list[str]:
    """Перечислить ключи сенсоров ядер процессора."""
    return [f"core_{core.index}" for core in data.activity.cores]


def _dynamic_keys(data: FastData) -> list[str]:
    """Перечислить ключи динамических сенсоров из последнего опроса."""
    keys: list[str] = []
    if data.system.cpu_temperature is not None:
        keys.append("cpu_temperature")
    keys.extend(f"fan_{index}" for index in range(1, len(data.system.fans) + 1))
    for network in data.activity.networks:
        if not network.enabled:
            continue
        keys.append(f"net_{network.name}_rx")
        keys.append(f"net_{network.name}_tx")
    for volume in data.volumes:
        keys.extend(
            f"volume_{volume.vid}_{kind}"
            for kind in ("capacity", "used", "used_percent")
        )
    for disk in data.disks:
        key = _disk_key(disk.did, disk.slot)
        keys.append(f"{key}_smart")
        if disk.temperature is not None:
            keys.append(f"{key}_temperature")
    for stat in data.activity.disks:
        key = _disk_key(stat.did, stat.slot)
        keys.extend(f"{key}_{kind}" for kind in ("read", "write"))
    return keys


def _build_dynamic_sensors(
    runtime: ADMRuntime, keys: Iterable[str]
) -> list[SensorEntity]:
    """Создать сенсоры для новых ключей динамических объектов."""
    data = runtime.fast_data
    entities: list[SensorEntity] = []
    cores = {f"core_{core.index}": core for core in data.activity.cores}
    networks = {network.name: network for network in data.activity.networks}
    volumes = {volume.vid: volume for volume in data.volumes}
    disks = {_disk_key(disk.did, disk.slot): disk for disk in data.disks}
    stats = {_disk_key(stat.did, stat.slot): stat for stat in data.activity.disks}

    for key in keys:
        if key in cores:
            index = cores[key].index
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key="cpu_core_usage",
                    placeholders={"index": index},
                    value_fn=lambda data, index=index: (
                        data.activity.cores[index - 1].usage
                        if len(data.activity.cores) >= index
                        else None
                    ),
                    unit=PERCENTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=1,
                    icon="mdi:cpu-64-bit",
                )
            )
        elif key == "cpu_temperature":
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix="cpu_temperature",
                    name_key="cpu_temperature",
                    placeholders={},
                    value_fn=lambda data: data.system.cpu_temperature,
                    device_class=SensorDeviceClass.TEMPERATURE,
                    unit=UnitOfTemperature.CELSIUS,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=1,
                )
            )
        elif key.startswith("fan_"):
            index = int(key.removeprefix("fan_")) - 1
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key="fan_speed",
                    placeholders={"index": index + 1},
                    value_fn=lambda data, index=index: (
                        data.system.fans[index]
                        if len(data.system.fans) > index
                        else None
                    ),
                    unit=REVOLUTIONS_PER_MINUTE,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=0,
                    icon="mdi:fan",
                )
            )
        elif key.startswith("net_"):
            name, _, direction = key[4:].rpartition("_")
            network = networks.get(name)
            if network is None:
                continue
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key=f"network_{direction}",
                    placeholders={"name": name},
                    value_fn=lambda data, name=name, direction=direction: (
                        _network_value(data, name, direction)
                    ),
                    device_class=SensorDeviceClass.DATA_RATE,
                    unit=_SPEED_UNIT,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=1,
                )
            )
        elif key.startswith("volume_"):
            _, raw_vid, kind = key.split("_", 2)
            vid = int(raw_vid)
            if vid not in volumes:
                continue
            entities.append(_build_volume_sensor(runtime, vid, kind))
        elif key.endswith("_temperature") and key.rpartition("_")[0] in disks:
            disk = disks[key.rpartition("_")[0]]
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key="disk_temperature",
                    placeholders={"disk": _disk_label(disk.did, disk.slot)},
                    value_fn=lambda data, did=disk.did: _disk_value(data, did, "temp"),
                    device_class=SensorDeviceClass.TEMPERATURE,
                    unit=UnitOfTemperature.CELSIUS,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=0,
                    attributes_fn=lambda runtime, did=disk.did, slot=disk.slot: (
                        _disk_attributes(runtime, did, slot)
                    ),
                )
            )
        elif key.endswith("_read") and key.rpartition("_")[0] in stats:
            stat = stats[key.rpartition("_")[0]]
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key="disk_read",
                    placeholders={"disk": _disk_label(stat.did, stat.slot)},
                    value_fn=lambda data, did=stat.did: _disk_stat_value(
                        data, did, "read"
                    ),
                    device_class=SensorDeviceClass.DATA_RATE,
                    unit=_SPEED_UNIT,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=1,
                )
            )
        elif key.endswith("_write") and key.rpartition("_")[0] in stats:
            stat = stats[key.rpartition("_")[0]]
            entities.append(
                ADMDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key="disk_write",
                    placeholders={"disk": _disk_label(stat.did, stat.slot)},
                    value_fn=lambda data, did=stat.did: _disk_stat_value(
                        data, did, "write"
                    ),
                    device_class=SensorDeviceClass.DATA_RATE,
                    unit=_SPEED_UNIT,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=1,
                )
            )
        elif key.endswith("_smart") and key.rpartition("_")[0] in disks:
            disk = disks[key.rpartition("_")[0]]
            entities.append(
                ADMSmartSensor(
                    runtime,
                    disk_id=disk.did,
                    slot=disk.slot,
                    placeholders={"disk": _disk_label(disk.did, disk.slot)},
                )
            )
    return entities


def _build_volume_sensor(runtime: ADMRuntime, vid: int, kind: str) -> SensorEntity:
    """Создать сенсор тома одного из трёх видов."""
    is_capacity = kind == "capacity"
    is_used = kind == "used"
    return ADMDynamicSensor(
        runtime,
        unique_suffix=f"volume_{vid}_{kind}",
        name_key=f"volume_{kind}",
        placeholders={"volume": vid},
        value_fn=lambda data, vid=vid, kind=kind: _volume_value(data, vid, kind),
        device_class=None
        if not (is_capacity or is_used)
        else SensorDeviceClass.DATA_SIZE,
        unit=None if not (is_capacity or is_used) else UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2 if (is_capacity or is_used) else 1,
        attributes_fn=lambda runtime, vid=vid: _volume_attributes(runtime, vid),
        also_listen_to=runtime.slow,
    )


def _volume_value(data: FastData, vid: int, kind: str) -> float | None:
    """Вернуть значение сенсора тома."""
    volume = data.volume(vid)
    if volume is None:
        return None
    if kind == "capacity":
        return bytes_to_gib(volume.capacity)
    if kind == "used":
        return bytes_to_gib(volume.used)
    return volume.used_percent


def _network_value(data: FastData, name: str, direction: str) -> float | None:
    """Вернуть скорость обмена сетевого интерфейса."""
    for network in data.activity.networks:
        if network.name == name:
            return network.rx if direction == "rx" else network.tx
    return None


def _disk_value(data: FastData, did: int, attribute: str) -> float | None:
    """Вернуть значение из сведений о диске."""
    for disk in data.disks:
        if disk.did == did:
            return disk.temperature if attribute == "temp" else getattr(disk, attribute)
    return None


def _disk_stat_value(data: FastData, did: int | None, attribute: str) -> float | None:
    """Вернуть скорость чтения или записи диска."""
    for stat in data.activity.disks:
        if stat.did == did:
            return stat.read if attribute == "read" else stat.write
    return None


class ADMSlowDynamicSensor(ADMSlowEntity, SensorEntity):
    """Сенсор объекта, появляющегося в медленном цикле опроса."""

    def __init__(
        self,
        runtime: ADMRuntime,
        *,
        unique_suffix: str,
        name_key: str,
        placeholders: dict[str, str | int],
        value_fn: Callable[[SlowData], Any],
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        precision: int | None = None,
        attributes_fn: Callable[[SlowData], dict[str, Any] | None] | None = None,
    ) -> None:
        """Создать динамический сенсор медленного цикла."""
        super().__init__(runtime, unique_suffix)
        self._attr_translation_key = name_key
        self._attr_translation_placeholders = {
            key: str(value) for key, value in placeholders.items()
        }
        self._value_fn = value_fn
        self._attributes_fn = attributes_fn
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class
        if precision is not None:
            self._attr_suggested_display_precision = precision

    @property
    def available(self) -> bool:
        """Быть недоступным, если внешний диск отключён."""
        alias = self._attr_translation_placeholders["disk"]
        return (
            super().available
            and any(
                disk.alias == alias for disk in self._runtime.slow_data.external_disks
            )
            and self.native_value is not None
        )

    @property
    def native_value(self) -> Any:
        """Вернуть значение из последнего опроса."""
        return self._value_fn(self._runtime.slow_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Вернуть сведения о внешнем диске."""
        if self._attributes_fn is None:
            return None
        return self._attributes_fn(self._runtime.slow_data)


def _external_attributes(data: SlowData, alias: str) -> dict[str, Any] | None:
    """Собрать сведения о внешнем диске для атрибутов."""
    for disk in data.external_disks:
        if disk.alias == alias:
            attributes = dict(disk.details)
            if disk.status is not None:
                attributes["status"] = disk.status
            return attributes
    return None


EXTERNAL_SENSOR_SUFFIXES = ("used_percent", "capacity", "free")


def _split_external_key(key: str) -> tuple[str, str]:
    """Разделить ключ внешнего диска на псевдоним и вид значения."""
    for suffix in EXTERNAL_SENSOR_SUFFIXES:
        if key.endswith(f"_{suffix}"):
            return key[len("extdisk_") : -(len(suffix) + 1)], suffix
    return "", ""


def _external_keys(data: SlowData) -> list[str]:
    """Ключи сенсоров внешних дисков."""
    keys: list[str] = []
    for disk in data.external_disks:
        keys.extend(
            (
                f"extdisk_{disk.alias}_capacity",
                f"extdisk_{disk.alias}_free",
                f"extdisk_{disk.alias}_used_percent",
            )
        )
    return keys


def _build_external_sensors(
    runtime: ADMRuntime, keys: Iterable[str]
) -> list[SensorEntity]:
    """Создать сенсоры ёмкости и заполнения внешних дисков."""
    entities: list[SensorEntity] = []
    known = {disk.alias for disk in runtime.slow_data.external_disks}
    for key in keys:
        alias, kind = _split_external_key(key)
        if alias not in known:
            continue
        if kind == "used_percent":
            entities.append(
                ADMSlowDynamicSensor(
                    runtime,
                    unique_suffix=key,
                    name_key="external_disk_used_percent",
                    placeholders={"disk": alias},
                    value_fn=lambda data, alias=alias, kind=kind: _external_value(
                        data, alias, kind
                    ),
                    unit=PERCENTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                    precision=1,
                    attributes_fn=lambda data, alias=alias: _external_attributes(
                        data, alias
                    ),
                )
            )
            continue
        entities.append(
            ADMSlowDynamicSensor(
                runtime,
                unique_suffix=key,
                name_key=f"external_disk_{kind}",
                placeholders={"disk": alias},
                value_fn=lambda data, alias=alias, kind=kind: _external_value(
                    data, alias, kind
                ),
                device_class=SensorDeviceClass.DATA_SIZE,
                unit=UnitOfInformation.GIBIBYTES,
                state_class=SensorStateClass.MEASUREMENT,
                precision=2,
                attributes_fn=lambda data, alias=alias: _external_attributes(
                    data, alias
                ),
            )
        )
    return entities


def _external_value(data: SlowData, alias: str, kind: str) -> float | None:
    """Вернуть значение сенсора внешнего диска."""
    for disk in data.external_disks:
        if disk.alias != alias:
            continue
        if kind == "capacity":
            return bytes_to_gib(disk.capacity)
        if kind == "free":
            return bytes_to_gib(disk.free)
        return disk.used_percent
    return None


@callback
def _remove_stale_core_entities(
    hass: HomeAssistant, runtime: ADMRuntime, manager: DynamicEntityManager[Any]
) -> None:
    """Удалить сущности ядер, которых больше нет в ответе ADM."""
    current = {f"core_{core.index}" for core in runtime.fast_data.activity.cores}
    registry = er.async_get(hass)
    for key in manager.known - current:
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, runtime.unique_id(key)
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
        manager.discard(key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать статические и динамические сенсоры записи."""
    runtime: ADMRuntime = entry.runtime_data
    entities: list[SensorEntity] = [
        ADMFastSensor(runtime, description, description.key)
        for description in FAST_SENSORS
    ]
    entities.extend(
        ADMSlowSensor(runtime, description, description.key)
        for description in SLOW_SENSORS
    )
    async_add_entities(entities)

    core_manager: DynamicEntityManager[SensorEntity] = DynamicEntityManager(
        async_add_entities,
        lambda keys: _build_dynamic_sensors(runtime, keys),
    )
    main_manager: DynamicEntityManager[SensorEntity] = DynamicEntityManager(
        async_add_entities,
        lambda keys: _build_dynamic_sensors(runtime, keys),
    )

    @callback
    def _sync_fast() -> None:
        """Привести набор сенсоров в соответствие с последним опросом."""
        data = runtime.fast_data
        core_manager.sync(_core_keys(data))
        _remove_stale_core_entities(hass, runtime, core_manager)
        main_manager.sync(_dynamic_keys(data))

    _sync_fast()
    entry.async_on_unload(runtime.fast.async_add_listener(_sync_fast))

    slow_manager: DynamicEntityManager[SensorEntity] = DynamicEntityManager(
        async_add_entities,
        lambda keys: _build_external_sensors(runtime, keys),
    )
    slow_manager.sync(_external_keys(runtime.slow_data))
    entry.async_on_unload(
        runtime.slow.async_add_listener(
            lambda: slow_manager.sync(_external_keys(runtime.slow_data))
        )
    )
