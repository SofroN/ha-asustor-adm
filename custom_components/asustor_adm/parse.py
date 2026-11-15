"""Разбор ответов ADM в модели данных.

Все парсеры устойчивы к отсутствующим и лишним полям: недостающее поле
даёт ``None``, а не исключение.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from .const import ServiceDefinition
from .models import (
    Activity,
    CpuCore,
    Disk,
    DiskStat,
    ExternalDisk,
    FirmwareInfo,
    NetworkInfo,
    NetworkStat,
    SmartAttributes,
    SysInfo,
    Volume,
)
from .values import to_flag, to_int, to_number, to_text

_CPU_KEY: Final = "cpu"
_SMART_REALLOCATED: Final = 5
_SMART_POWER_ON_HOURS: Final = 9
_SMART_TEMPERATURE: Final = 194
_SMART_PENDING: Final = 197

_POWER_ON_HOURS_RE: Final = re.compile(
    r"^\s*(?P<hours>\d+)\s*h(?:\s*\+\s*(?P<minutes>\d+)\s*m)?"
    r"(?:\s*\+\s*(?P<seconds>[\d.]+)\s*s)?\s*$"
)
_FINISHED_TASK_STATES: Final = frozenset(
    {"ended", "finished", "complete", "completed", "done"}
)


def _items(payload: Mapping[str, Any] | None, key: str) -> list[Mapping[str, Any]]:
    """Вернуть список объектов из поля ответа, если оно является списком."""
    if not isinstance(payload, Mapping):
        return []
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping(payload: Any) -> Mapping[str, Any]:
    """Вернуть ответ как отображение или пустое отображение."""
    return payload if isinstance(payload, Mapping) else {}


def parse_sysinfo(payload: Mapping[str, Any] | None) -> SysInfo:
    """Разобрать ответ `sysinfo.cgi?act=sys`."""
    data = _mapping(payload)
    fans_payload = data.get("fan_speed")
    fans: tuple[float, ...] = ()
    if isinstance(fans_payload, list):
        parsed = [to_number(value) for value in fans_payload]
        fans = tuple(value for value in parsed if value is not None)
    return SysInfo(
        model=to_text(data.get("model")),
        serial=to_text(data.get("serial")),
        adm_version=to_text(data.get("os")),
        bios=to_text(data.get("bios")),
        cpu_model=to_text(data.get("cpu")),
        cpu_temperature=to_number(data.get("cputemp")),
        fans=fans,
        uptime=to_number(data.get("uptime")),
    )


def parse_activity(payload: Mapping[str, Any] | None) -> Activity:
    """Разобрать ответ `activityMonitor/act.cgi?act=list`."""
    data = _mapping(payload)

    cores: list[CpuCore] = []
    for index, item in enumerate(_items(data, "cpus"), start=1):
        cores.append(CpuCore(index=index, usage=to_number(item.get("usage"))))
    usages = [core.usage for core in cores if core.usage is not None]
    cpu_total = round(sum(usages) / len(usages), 1) if usages else None

    networks: list[NetworkStat] = []
    for item in _items(data, "net"):
        name = to_text(item.get("name"))
        if name is None:
            continue
        networks.append(
            NetworkStat(
                name=name,
                enabled=bool(to_flag(item.get("enable"))),
                rx=to_number(item.get("rx")),
                tx=to_number(item.get("tx")),
            )
        )

    disks: list[DiskStat] = []
    for item in _items(data, "disks"):
        disks.append(
            DiskStat(
                did=to_int(item.get("did")),
                slot=to_int(item.get("slot")),
                read=to_number(item.get("read")),
                write=to_number(item.get("write")),
            )
        )

    return Activity(
        cpu_total=cpu_total,
        cores=tuple(cores),
        load_1=to_number(data.get("avgload1")),
        load_5=to_number(data.get("avgload5")),
        load_15=to_number(data.get("avgload15")),
        memory_total_kb=to_number(data.get("memtotal")),
        memory_used_kb=to_number(data.get("memused")),
        networks=tuple(networks),
        disks=tuple(disks),
    )


def _parse_volume_base(item: Mapping[str, Any]) -> Volume | None:
    """Разобрать том из ответа со списком томов."""
    vid = to_int(item.get("vid"))
    if vid is None:
        return None
    dids = tuple(
        did
        for did in (to_int(disk.get("did")) for disk in _items(item, "disks"))
        if did is not None
    )
    return Volume(
        vid=vid,
        level=to_text(item.get("level")),
        state=to_text(item.get("state")),
        fstype=to_text(item.get("fstype")),
        capacity=to_int(item.get("capacity")),
        used=to_int(item.get("used")),
        disk_dids=dids,
    )


def parse_volumes(payload: Mapping[str, Any] | None) -> tuple[Volume, ...]:
    """Разобрать ответ `volume.cgi?act=list`."""
    volumes = (_parse_volume_base(item) for item in _items(payload, "volumes"))
    return tuple(volume for volume in volumes if volume is not None)


def parse_volume_details(
    payload: Mapping[str, Any] | None,
) -> Volume | None:
    """Разобрать ответ `volume.cgi?act=get` со сведениями RAID."""
    data = _mapping(payload)
    base = _parse_volume_base(data)
    if base is None:
        return None
    return Volume(
        vid=base.vid,
        level=base.level,
        state=base.state,
        fstype=base.fstype,
        capacity=base.capacity,
        used=base.used,
        members=to_int(data.get("member")),
        failed=to_int(data.get("failed")),
        removed=to_int(data.get("removed")),
        spare=to_int(data.get("spare")),
        redundant=to_int(data.get("redundant")),
        disk_dids=base.disk_dids,
    )


def parse_disks(payload: Mapping[str, Any] | None) -> tuple[Disk, ...]:
    """Разобрать ответ `disk_smart.cgi?act=list`."""
    disks: list[Disk] = []
    for item in _items(payload, "disks"):
        did = to_int(item.get("did"))
        if did is None:
            continue
        disks.append(
            Disk(
                did=did,
                dev=to_text(item.get("dev")),
                model=to_text(item.get("model")),
                serial=to_text(item.get("serial")),
                firmware=to_text(item.get("fwver")),
                slot=to_int(item.get("slot")),
                disk_type=to_text(item.get("type")),
                size_bytes=to_int(item.get("size")),
                temperature=to_number(item.get("temp")),
                state=to_text(item.get("state")),
                smart_status=to_text(item.get("smart_status")),
                error=to_text(item.get("error")),
                badblock=to_text(item.get("badblock")),
                volume=to_text(item.get("volume")),
            )
        )
    return tuple(disks)


def parse_power_on_hours(value: Any) -> float | None:
    """Привести наработку в часах к числу часов.

    Поддерживаются форматы ``42841`` и ``17678h+41m+50.811s``.
    """
    number = to_number(value)
    if number is not None:
        return number
    text = to_text(value)
    if text is None:
        return None
    match = _POWER_ON_HOURS_RE.match(text)
    if match is None:
        return None
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return round(hours + minutes / 60 + seconds / 3600, 2)


def parse_smart(payload: Mapping[str, Any] | None) -> SmartAttributes | None:
    """Разобрать ответ `disk_smart.cgi?act=smart`."""
    infos = _items(payload, "infos")
    if not infos:
        return None
    raw: dict[str, str] = {}
    values: dict[int, Any] = {}
    for item in infos:
        attribute_id = to_int(item.get("id"))
        name = to_text(item.get("attribute"))
        raw_value = item.get("raw_value")
        if name is not None and raw_value is not None:
            raw[name] = str(raw_value).strip()
        if attribute_id is not None:
            values[attribute_id] = raw_value
    return SmartAttributes(
        reallocated_sectors=to_number(values.get(_SMART_REALLOCATED)),
        pending_sectors=to_number(values.get(_SMART_PENDING)),
        temperature=to_number(values.get(_SMART_TEMPERATURE)),
        power_on_hours=parse_power_on_hours(values.get(_SMART_POWER_ON_HOURS)),
        attributes=raw,
    )


def parse_external_disks(
    payload: Mapping[str, Any] | None,
) -> tuple[ExternalDisk, ...]:
    """Разобрать ответ `extdisk.cgi?act=list`."""
    disks: list[ExternalDisk] = []
    for item in _items(payload, "disks"):
        alias = to_text(item.get("alias"))
        if alias is None:
            continue
        disks.append(
            ExternalDisk(
                alias=alias,
                status=to_text(item.get("status")),
                vendor=to_text(item.get("vendor")),
                model=to_text(item.get("model")),
                connection_type=to_text(item.get("type")),
                fstype=to_text(item.get("fstype")),
                capacity=to_int(item.get("capacity")),
                free=to_int(item.get("free")),
                slot=to_int(item.get("slot")),
                device_size=to_int(item.get("devicesize")),
            )
        )
    return tuple(disks)


def parse_network_info(payload: Mapping[str, Any] | None) -> NetworkInfo:
    """Разобрать ответ `sysinfo.cgi?act=net`."""
    data = _mapping(payload)
    interfaces = _items(data, "netif")
    primary: Mapping[str, Any] = {}
    for item in interfaces:
        if to_flag(item.get("status")):
            primary = item
            break
    if not primary and interfaces:
        primary = interfaces[0]
    dns_raw = to_text(data.get("dns")) or ""
    return NetworkInfo(
        ipv4=to_text(primary.get("ipv4")),
        ipv6=to_text(primary.get("ipv6")),
        mac=to_text(primary.get("mac")),
        gateway=to_text(data.get("gwip")),
        dns=tuple(dns_raw.split()),
    )


def parse_wan_ip(payload: Mapping[str, Any] | None) -> str | None:
    """Разобрать ответ `sysinfo.cgi?act=wan`."""
    return to_text(_mapping(payload).get("wanip"))


def parse_sessions(payload: Mapping[str, Any] | None) -> int | None:
    """Разобрать ответ `onlineuser.cgi?act=list`."""
    data = _mapping(payload)
    total = to_int(data.get("total"))
    if total is not None:
        return total
    return len(_items(data, "datas"))


def parse_tasks(payload: Mapping[str, Any] | None) -> int | None:
    """Посчитать незавершённые задачи из ответа `taskmonitor.cgi?act=task_list`."""
    data = _mapping(payload)
    if "data" not in data and "total" in data:
        return to_int(data.get("total"))
    tasks = _items(data, "data")
    if "data" not in data:
        return None
    return sum(
        1
        for task in tasks
        if (to_text(task.get("status")) or "").lower() not in _FINISHED_TASK_STATES
    )


def parse_firmware(payload: Mapping[str, Any] | None) -> FirmwareInfo:
    """Разобрать ответ `firmwarestatus.cgi?act=get_static_info`."""
    data = _mapping(payload)
    target = (
        to_text(data.get("new_version"))
        or to_text(data.get("latest_version"))
        or to_text(data.get("available_version"))
    )
    return FirmwareInfo(
        installed_version=to_text(data.get("installed_version")),
        update_available=to_flag(data.get("update_available_notification")),
        target_version=target,
    )


def parse_app_updates(payload: Mapping[str, Any] | None) -> int | None:
    """Разобрать ответ `appcentral.cgi?act=count`."""
    return to_int(_mapping(payload).get("total"))


def parse_service_state(
    payload: Mapping[str, Any] | None, definition: ServiceDefinition
) -> bool | None:
    """Извлечь признак включения сервиса из ответа его эндпоинта."""
    data = _mapping(payload)
    if definition.field not in data:
        return None
    return to_flag(data.get(definition.field))
