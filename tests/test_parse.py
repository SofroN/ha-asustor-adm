"""Разбор фикстур спайка (задачи 2.4, 2.5)."""

from __future__ import annotations

import pytest
from helpers import FIXTURES_DIR, load_fixture

from custom_components.asustor_adm.const import SERVICE_DEFINITIONS
from custom_components.asustor_adm.parse import (
    parse_activity,
    parse_app_updates,
    parse_disks,
    parse_external_disks,
    parse_firmware,
    parse_power_on_hours,
    parse_service_state,
    parse_sessions,
    parse_smart,
    parse_sysinfo,
    parse_tasks,
    parse_volume_details,
    parse_volumes,
)


def test_parse_sysinfo() -> None:
    """Сведения об устройстве разбираются из ответа sysinfo."""
    system = parse_sysinfo(load_fixture("sysinfo"))
    assert system.model == "AS3304T"
    assert system.serial == "SN012345678"
    assert system.adm_version == "5.1.4.RM62"
    assert system.bios == "1.14"
    assert system.cpu_temperature == 58
    assert system.fans == (776,)
    assert system.uptime == 1672376


def test_parse_sysinfo_without_temperature() -> None:
    """Модель без датчика температуры не даёт значения температуры."""
    system = parse_sysinfo(load_fixture("sysinfo_no_temperature"))
    assert system.cpu_temperature is None
    assert system.fans == (776,)


def test_parse_sysinfo_two_fans() -> None:
    """Массив кулеров разбирается целиком."""
    assert parse_sysinfo(load_fixture("sysinfo_two_fans")).fans == (776, 812)


def test_parse_activity_cpu_and_load() -> None:
    """Загрузка по ядрам, средняя загрузка и нагрузки разбираются."""
    activity = parse_activity(load_fixture("activity"))
    assert [core.index for core in activity.cores] == [1, 2, 3, 4]
    assert [core.usage for core in activity.cores] == [4, 3, 5, 3]
    assert activity.cpu_total == 3.8
    assert activity.load_1 == 2.28
    assert activity.load_15 == 2.22


def test_parse_activity_memory() -> None:
    """Память разбирается в килобайтах, доля считается из двух величин."""
    activity = parse_activity(load_fixture("activity"))
    assert activity.memory_total_kb == 1983612
    assert activity.memory_used_kb == 693264
    assert activity.memory_used_percent == 34.9


def test_parse_activity_networks() -> None:
    """В сетевом списке остаются все интерфейсы с признаком включения."""
    activity = parse_activity(load_fixture("activity"))
    lan = activity.networks[0]
    assert (lan.name, lan.enabled, lan.rx, lan.tx) == ("Lan1", True, 1, 1)
    assert [network.name for network in activity.networks] == [
        "Lan1",
        "Wifi",
        "Usb4Net1",
        "Usb4Net2",
    ]
    assert activity.networks[1].enabled is False


def test_parse_activity_disk_speeds() -> None:
    """Скорости чтения и записи дисков разбираются по каждому диску."""
    activity = parse_activity(load_fixture("activity_write"))
    assert activity.disks[0].read == 0
    assert activity.disks[0].write == 22155
    assert activity.disks[1].write == 12018


def test_parse_activity_foreign_structure() -> None:
    """Неожиданная структура ответа не приводит к исключению."""
    activity = parse_activity(load_fixture("activity_foreign_structure"))
    assert activity.cpu_total is None
    assert activity.cores == ()
    assert activity.networks == ()


def test_parse_volumes() -> None:
    """Тома разбираются вместе с уровнем и заполнением."""
    volumes = parse_volumes(load_fixture("volumes"))
    assert [volume.vid for volume in volumes] == [1, 2]
    assert [volume.level for volume in volumes] == ["single", "raid1"]
    assert volumes[0].capacity == 7932738306048
    assert volumes[0].used_percent == 59.8
    assert volumes[0].healthy is True


def test_parse_volumes_without_used() -> None:
    """Том без занятого объёма публикует ёмкость без доли заполнения."""
    volume = parse_volumes(load_fixture("volumes_without_used"))[0]
    assert volume.capacity == 7932738306048
    assert volume.used is None
    assert volume.used_percent is None


def test_parse_volume_details_raid1() -> None:
    """Сведения RAID содержат участников, резерв и отказы."""
    volume = parse_volume_details(load_fixture("volume_2"))
    assert volume is not None
    assert volume.level == "raid1"
    assert volume.members == 2
    assert volume.spare == 1
    assert volume.failed == 0
    assert volume.raid_attributes["has_spare"] is True


def test_parse_volume_details_single_has_no_raid_attributes() -> None:
    """Одиночный том публикуется без атрибутов RAID."""
    volume = parse_volume_details(load_fixture("volume_1"))
    assert volume is not None
    assert volume.raid_attributes == {}


def test_parse_volumes_degraded() -> None:
    """Деградация массива даёт проблему тома."""
    volume = parse_volumes(load_fixture("volumes_degraded"))[1]
    assert volume.state == "degraded"
    assert volume.healthy is False


def test_parse_disks() -> None:
    """Диски разбираются со слотами, температурой и здоровьем."""
    disks = parse_disks(load_fixture("disks"))
    assert len(disks) == 4
    assert disks[0].slot == 1
    assert disks[0].temperature == 40
    assert disks[0].details["model"] == "ST2000DM008-2FR102"
    assert disks[0].healthy is True
    assert disks[2].volume is None


def test_parse_disks_smart_warning() -> None:
    """Предупреждение SMART делает диск проблемным."""
    disks = parse_disks(load_fixture("disks_smart_warning"))
    assert disks[0].healthy is True
    assert disks[1].smart_status == "Warning"
    assert disks[1].healthy is False


def test_parse_disks_without_temperature() -> None:
    """Диск без датчика температуры не даёт значения температуры."""
    disks = parse_disks(load_fixture("disks_no_temperature"))
    assert disks[1].temperature is None


def test_parse_smart_selected_attributes() -> None:
    """Из набора SMART выделяются переназначенные секторы и наработка."""
    smart = parse_smart(load_fixture("smart"))
    assert smart is not None
    assert smart.reallocated_sectors == 0
    assert smart.pending_sectors == 0
    assert smart.temperature == 40
    assert smart.power_on_hours == pytest.approx(17678.7, abs=0.1)
    assert smart.attributes["Reallocated_Sector_Ct"] == "0"


def test_parse_smart_empty_payload() -> None:
    """Пустой набор атрибутов не даёт исключения."""
    assert parse_smart({"success": True, "infos": []}) is None


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("smart_hours_integer", 42841),
        ("smart", pytest.approx(17678.7, abs=0.1)),
        ("smart_empty_hours", None),
    ],
)
def test_parse_power_on_hours_formats(fixture: str, expected: object) -> None:
    """Наработка приводится к часам в трёх форматах значения."""
    smart = parse_smart(load_fixture(fixture))
    assert smart is not None
    if isinstance(expected, float):
        assert smart.power_on_hours == pytest.approx(expected, abs=0.1)
    else:
        assert smart.power_on_hours == expected


@pytest.mark.parametrize("value", ["", None, "n/a"])
def test_parse_power_on_hours_empty(value: object) -> None:
    """Пустое или нечисловое значение наработки не даёт числа."""
    assert parse_power_on_hours(value) is None


def test_parse_external_disks() -> None:
    """Внешние диски разбираются с ёмкостью и свободным местом."""
    disks = parse_external_disks(load_fixture("extdisks"))
    assert [disk.alias for disk in disks] == ["USB2", "USB31"]
    assert disks[0].ready is True
    assert disks[0].details["vendor"] == "WDC"
    assert disks[0].used_percent == 96.2
    assert parse_external_disks(load_fixture("extdisks_empty")) == ()


def test_parse_external_disk_ejecting() -> None:
    """Диск в состоянии извлечения не готов к работе."""
    disk = parse_external_disks(load_fixture("extdisks_ejecting"))[0]
    assert disk.status == "ejecting"
    assert disk.ready is False


def test_parse_sessions() -> None:
    """Число активных сессий берётся из поля total."""
    assert parse_sessions(load_fixture("sessions")) == 1
    assert parse_sessions(load_fixture("sessions_empty")) == 0


def test_parse_tasks() -> None:
    """Незавершённые задачи считаются активными."""
    assert parse_tasks(load_fixture("tasks")) == 0
    assert parse_tasks(load_fixture("tasks_running")) == 1


def test_parse_firmware() -> None:
    """Установленная версия и признак обновления разбираются."""
    firmware = parse_firmware(load_fixture("firmware"))
    assert firmware.installed_version == "5.1.4.RM62"
    assert firmware.update_available is True
    assert firmware.target_version is None


def test_parse_firmware_up_to_date() -> None:
    """Отсутствие обновлений даёт значение False, а не None."""
    assert parse_firmware(load_fixture("firmware_up_to_date")).update_available is False


def test_parse_firmware_with_target() -> None:
    """Подтверждённая целевая версия попадает в разобранные сведения."""
    assert parse_firmware(load_fixture("firmware_with_target")).target_version == (
        "5.1.5.RN11"
    )


def test_parse_app_updates() -> None:
    """Счётчик обновлений App Central разбирается."""
    assert parse_app_updates(load_fixture("appcentral")) == 0
    assert parse_app_updates(load_fixture("appcentral_updates")) == 3


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("service_smb", True),
        ("service_smb_off", False),
        ("service_nfs", True),
        ("service_ftp", True),
        ("service_webdav", True),
        ("service_terminal", False),
        ("service_rsync", True),
        ("service_rsync_off", False),
        ("service_snmp", True),
        ("service_tftp", False),
    ],
)
def test_parse_service_state(fixture: str, expected: bool) -> None:
    """Признак включения сервиса разбирается из разнородных полей."""
    key = {
        "service_smb": "smb",
        "service_smb_off": "smb",
        "service_nfs": "nfs",
        "service_ftp": "ftp",
        "service_webdav": "webdav",
        "service_terminal": "ssh",
        "service_rsync": "rsync",
        "service_rsync_off": "rsync",
        "service_snmp": "snmp",
        "service_tftp": "tftp",
    }[fixture]
    definition = next(item for item in SERVICE_DEFINITIONS if item.key == key)
    assert parse_service_state(load_fixture(fixture), definition) is expected


def test_parse_service_missing_field() -> None:
    """Сервис, сведений о котором нет, не даёт значения."""
    definition = next(item for item in SERVICE_DEFINITIONS if item.key == "sftp")
    assert (
        parse_service_state(load_fixture("service_terminal_ssh_only"), definition)
        is None
    )


def test_all_fixtures_are_parsed_without_exceptions() -> None:
    """Каждая фикстура спайка разбирается всеми парсерами без исключений."""
    parsers = (
        parse_sysinfo,
        parse_activity,
        parse_volumes,
        parse_volume_details,
        parse_disks,
        parse_smart,
        parse_external_disks,
        parse_sessions,
        parse_tasks,
        parse_firmware,
        parse_app_updates,
    )
    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    assert fixtures, "каталог фикстур пуст"
    for path in fixtures:
        payload = load_fixture(path.stem)
        for parser in parsers:
            parser(payload)
    assert any(
        parse_service_state(load_fixture("service_smb"), definition) is True
        for definition in SERVICE_DEFINITIONS
    )
