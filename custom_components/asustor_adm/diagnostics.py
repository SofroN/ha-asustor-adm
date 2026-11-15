"""Диагностика записи ASUSTOR NAS (ADM)."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from .entity import ADMRuntime

TO_REDACT: Final = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_HOST,
    "password",
    "sid",
    "passport",
    "account",
    "serial",
    "serial_number",
    "ip",
    "ipv4",
    "ipv6",
    "wanip",
    "dns",
    "dns2",
    "gwip",
}


def _last_error(coordinator: Any) -> str | None:
    """Вернуть текст последней ошибки координатора без параметров запроса."""
    error = getattr(coordinator, "last_exception", None)
    if error is None:
        return None
    return f"{type(error).__name__}: {error}"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Собрать диагностику записи без секретов и идентификаторов сессии."""
    runtime: ADMRuntime | None = getattr(entry, "runtime_data", None)
    diagnostics: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
    }
    if runtime is None:
        diagnostics["runtime"] = None
        return diagnostics

    system = runtime.system
    fast = runtime.fast_data
    slow = runtime.slow_data
    diagnostics.update(
        {
            "device": async_redact_data(
                {
                    "model": system.model,
                    "serial": system.serial,
                    "adm_version": system.adm_version,
                    "bios": system.bios,
                    "cpu_model": system.cpu_model,
                },
                TO_REDACT,
            ),
            "coordinators": {
                "fast": {
                    "last_update_success": runtime.fast.last_update_success,
                    "update_interval": str(runtime.fast.update_interval),
                    "cycle_requests": runtime.fast.last_cycle_requests,
                    "degraded_requests": runtime.fast.cycle_errors,
                    "last_error": _last_error(runtime.fast),
                },
                "slow": {
                    "last_update_success": runtime.slow.last_update_success,
                    "update_interval": str(runtime.slow.update_interval),
                    "cycle_requests": runtime.slow.last_cycle_requests,
                    "degraded_requests": runtime.slow.cycle_errors,
                    "last_error": _last_error(runtime.slow),
                },
            },
            "services": dict(sorted(slow.services.items())),
            "firmware": {
                "installed_version": slow.firmware.installed_version,
                "update_available": slow.firmware.update_available,
                "target_version": slow.firmware.target_version,
                "last_check_error": slow.firmware.last_check_error,
            },
            "counts": {
                "volumes": len(fast.volumes),
                "disks": len(fast.disks),
                "external_disks": len(slow.external_disks),
                "cpu_cores": len(fast.activity.cores),
                "fans": len(system.fans),
                "sessions": slow.sessions,
            },
            "permissions": {
                "is_admin": runtime.is_admin,
                "can_suspend": runtime.can_suspend,
            },
        }
    )
    return diagnostics
