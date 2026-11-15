"""Разобранные данные ответов ADM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .values import ratio_percent


@dataclass(frozen=True, slots=True)
class SysInfo:
    """Сведения об устройстве из `sysinfo.cgi?act=sys`."""

    model: str | None = None
    serial: str | None = None
    adm_version: str | None = None
    bios: str | None = None
    cpu_model: str | None = None
    cpu_temperature: float | None = None
    fans: tuple[float, ...] = ()
    uptime: float | None = None


@dataclass(frozen=True, slots=True)
class CpuCore:
    """Загрузка отдельного ядра процессора."""

    index: int
    usage: float | None


@dataclass(frozen=True, slots=True)
class NetworkStat:
    """Скорости обмена одного сетевого интерфейса в килобайтах в секунду."""

    name: str
    enabled: bool
    rx: float | None
    tx: float | None


@dataclass(frozen=True, slots=True)
class DiskStat:
    """Скорости обмена одного диска в килобайтах в секунду."""

    did: int | None
    slot: int | None
    read: float | None
    write: float | None


@dataclass(frozen=True, slots=True)
class Activity:
    """Метрики ресурсов из `activityMonitor/act.cgi?act=list`."""

    cpu_total: float | None = None
    cores: tuple[CpuCore, ...] = ()
    load_1: float | None = None
    load_5: float | None = None
    load_15: float | None = None
    memory_total_kb: float | None = None
    memory_used_kb: float | None = None
    networks: tuple[NetworkStat, ...] = ()
    disks: tuple[DiskStat, ...] = ()

    @property
    def memory_used_percent(self) -> float | None:
        """Доля использованной памяти в процентах."""
        return ratio_percent(self.memory_used_kb, self.memory_total_kb)


@dataclass(frozen=True, slots=True)
class Volume:
    """Том NAS со сведениями RAID."""

    vid: int
    level: str | None = None
    state: str | None = None
    fstype: str | None = None
    capacity: int | None = None
    used: int | None = None
    members: int | None = None
    failed: int | None = None
    removed: int | None = None
    spare: int | None = None
    redundant: int | None = None
    disk_dids: tuple[int, ...] = ()

    @property
    def used_percent(self) -> float | None:
        """Доля занятого места тома в процентах."""
        return ratio_percent(self.used, self.capacity)

    @property
    def healthy(self) -> bool | None:
        """Признак исправности тома."""
        if self.state is None:
            return None
        return self.state.lower() == "healthy"

    @property
    def raid_attributes(self) -> dict[str, object]:
        """Атрибуты RAID для публикации в сущности тома."""
        attributes: dict[str, object] = {}
        if self.level is None or self.level.lower() in {"single", "linear", "none"}:
            return attributes
        attributes["level"] = self.level
        for key, value in (
            ("members", self.members),
            ("failed", self.failed),
            ("removed", self.removed),
            ("spare", self.spare),
            ("redundant", self.redundant),
        ):
            if value is not None:
                attributes[key] = value
        if self.spare is not None:
            attributes["has_spare"] = self.spare > 0
        return attributes


@dataclass(frozen=True, slots=True)
class Disk:
    """Установленный внутренний диск."""

    did: int
    dev: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    slot: int | None = None
    disk_type: str | None = None
    size_bytes: int | None = None
    temperature: float | None = None
    state: str | None = None
    smart_status: str | None = None
    error: str | None = None
    badblock: str | None = None
    volume: str | None = None

    @property
    def healthy(self) -> bool | None:
        """Признак отсутствия проблем у диска."""
        checks: list[bool] = []
        if self.state is not None:
            checks.append(self.state.lower() in {"normal", "healthy"})
        if self.smart_status is not None:
            checks.append(self.smart_status.lower() in {"healthy", "good", "ok"})
        if self.error is not None:
            checks.append(self.error.lower() in {"none", "no_error", ""})
        if self.badblock is not None:
            checks.append(self.badblock.lower() in {"no_error", "none"})
        if not checks:
            return None
        return all(checks)

    @property
    def details(self) -> dict[str, object]:
        """Сведения о диске для публикации в атрибутах."""
        attributes: dict[str, object] = {}
        for key, value in (
            ("model", self.model),
            ("serial", self.serial),
            ("firmware", self.firmware),
            ("slot", self.slot),
            ("type", self.disk_type),
            ("volume", self.volume),
        ):
            if value is not None:
                attributes[key] = value
        return attributes


@dataclass(frozen=True, slots=True)
class SmartAttributes:
    """Избранные атрибуты SMART, полученные по запросу."""

    reallocated_sectors: float | None = None
    pending_sectors: float | None = None
    temperature: float | None = None
    power_on_hours: float | None = None
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExternalDisk:
    """Внешний диск, подключённый по USB."""

    alias: str
    status: str | None = None
    vendor: str | None = None
    model: str | None = None
    connection_type: str | None = None
    fstype: str | None = None
    capacity: int | None = None
    free: int | None = None
    slot: int | None = None
    device_size: int | None = None

    @property
    def ready(self) -> bool | None:
        """Признак готовности внешнего диска к работе."""
        if self.status is None:
            return None
        return self.status.lower() == "ready"

    @property
    def used_percent(self) -> float | None:
        """Доля занятого места внешнего диска в процентах."""
        if self.capacity is None or self.free is None:
            return None
        return ratio_percent(self.capacity - self.free, self.capacity)

    @property
    def details(self) -> dict[str, object]:
        """Сведения о внешнем диске для публикации в атрибутах."""
        attributes: dict[str, object] = {}
        for key, value in (
            ("model", self.model),
            ("vendor", self.vendor),
            ("connection_type", self.connection_type),
            ("filesystem", self.fstype),
            ("slot", self.slot),
        ):
            if value is not None:
                attributes[key] = value
        return attributes


@dataclass(frozen=True, slots=True)
class NetworkInfo:
    """Сетевые сведения NAS из `sysinfo.cgi?act=net`."""

    ipv4: str | None = None
    ipv6: str | None = None
    mac: str | None = None
    gateway: str | None = None
    dns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FirmwareInfo:
    """Состояние прошивки ADM.

    ``update_available`` вычисляется после сведения с предыдущим состоянием:
    ответ ADM подтверждает обновление только целевой версией, поэтому
    ``None`` означает «неизвестно», а не «обновлений нет».
    """

    installed_version: str | None = None
    update_available: bool | None = None
    target_version: str | None = None
    last_check_error: int | None = None
    notification_flag: bool | None = None
    last_check_time: str | None = None


@dataclass(frozen=True, slots=True)
class FastData:
    """Результат быстрого цикла опроса."""

    system: SysInfo = field(default_factory=SysInfo)
    activity: Activity = field(default_factory=Activity)
    volumes: tuple[Volume, ...] = ()
    disks: tuple[Disk, ...] = ()

    def volume(self, vid: int) -> Volume | None:
        """Найти том по идентификатору."""
        for volume in self.volumes:
            if volume.vid == vid:
                return volume
        return None

    def disk(self, did: int) -> Disk | None:
        """Найти диск по идентификатору."""
        for disk in self.disks:
            if disk.did == did:
                return disk
        return None


@dataclass(frozen=True, slots=True)
class SlowData:
    """Результат медленного цикла опроса."""

    services: Mapping[str, bool | None] = field(default_factory=dict)
    sessions: int | None = None
    tasks: int | None = None
    firmware: FirmwareInfo = field(default_factory=FirmwareInfo)
    network: NetworkInfo = field(default_factory=NetworkInfo)
    wan_ip: str | None = None
    app_updates: int | None = None
    external_disks: tuple[ExternalDisk, ...] = ()
    volumes: Mapping[int, Volume] = field(default_factory=dict)
