"""Вспомогательные функции тестов интеграции ASUSTOR ADM."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from custom_components.asustor_adm.const import (
    END_ACTIVITY,
    END_APP_UPDATES,
    END_DISK_LIST,
    END_DISK_SMART,
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
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Прочитать фикстуру ответа ADM по имени."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def default_routes() -> dict[tuple[str, str | None], dict[str, Any]]:
    """Собрать таблицу ответов по умолчанию для всех эндпоинтов."""
    routes: dict[tuple[str, str | None], dict[str, Any]] = {
        (END_ACTIVITY.path, END_ACTIVITY.act): load_fixture("activity"),
        (END_SYSINFO.path, END_SYSINFO.act): load_fixture("sysinfo"),
        (END_SYSINFO_NET.path, END_SYSINFO_NET.act): load_fixture("sysinfo_net"),
        (END_SYSINFO_WAN.path, END_SYSINFO_WAN.act): load_fixture("sysinfo_wan"),
        (END_VOLUME_LIST.path, END_VOLUME_LIST.act): load_fixture("volumes"),
        (END_VOLUME_GET.path, END_VOLUME_GET.act): load_fixture("volume_1"),
        (END_DISK_LIST.path, END_DISK_LIST.act): load_fixture("disks"),
        (END_DISK_SMART.path, END_DISK_SMART.act): load_fixture("smart"),
        (END_SESSIONS.path, END_SESSIONS.act): load_fixture("sessions"),
        (END_TASKS.path, END_TASKS.act): load_fixture("tasks"),
        (END_EXT_DISK.path, END_EXT_DISK.act): load_fixture("extdisks"),
        (END_FIRMWARE.path, END_FIRMWARE.act): load_fixture("firmware"),
        (END_APP_UPDATES.path, END_APP_UPDATES.act): load_fixture("appcentral"),
    }
    service_fixtures = {
        "windows": "service_smb",
        "nfs": "service_nfs",
        "ftp": "service_ftp",
        "http": "service_webdav",
        "terminal": "service_terminal",
        "rsync": "service_rsync",
        "snmp": "service_snmp",
        "tftp_server": "service_tftp",
    }
    for definition in SERVICE_DEFINITIONS:
        fixture = service_fixtures[definition.endpoint.name.removesuffix(".cgi")]
        routes[(definition.endpoint.path, definition.endpoint.act)] = load_fixture(
            fixture
        )
    return routes


async def setup_integration(hass: Any, entry: Any) -> None:
    """Настроить запись интеграции и дождаться создания сущностей."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
