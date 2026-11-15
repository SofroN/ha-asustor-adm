"""Проверки констант интеграции (задача 1.2)."""

from __future__ import annotations

from custom_components.asustor_adm.const import (
    API_ROOT,
    END_ACTIVITY,
    END_LOGIN,
    END_POWER,
    ERROR_CODES,
    FAST_CYCLE_ENDPOINTS,
    SERVICE_DEFINITIONS,
    SERVICE_ENDPOINTS,
    SERVICE_KEYS,
    SLOW_CYCLE_STATIC_ENDPOINTS,
    Endpoint,
)


def test_domain_and_endpoint_path() -> None:
    """Путь эндпоинта собирается из модуля и имени."""
    assert Endpoint("storageManager", "volume.cgi").path == (
        f"{API_ROOT}/storageManager/volume.cgi"
    )
    assert END_LOGIN.path == f"{API_ROOT}/login.cgi"
    assert END_POWER.path == f"{API_ROOT}/admin.cgi"
    assert END_ACTIVITY.path == f"{API_ROOT}/activityMonitor/act.cgi"


def test_error_codes_have_no_duplicates() -> None:
    """Коды ошибок уникальны и содержат ожидаемый набор."""
    assert len(ERROR_CODES) == len(set(ERROR_CODES))
    assert {5000, 5005, 6209, 6215, 6300} == ERROR_CODES


def test_fast_cycle_endpoints_are_unique() -> None:
    """Быстрый цикл содержит четыре уникальных эндпоинта."""
    assert len(FAST_CYCLE_ENDPOINTS) == 4
    assert len(set(FAST_CYCLE_ENDPOINTS)) == 4


def test_slow_cycle_endpoints_are_unique() -> None:
    """Медленный цикл не содержит повторов среди статических запросов."""
    unique = set(SLOW_CYCLE_STATIC_ENDPOINTS) | set(SERVICE_ENDPOINTS)
    assert len(unique) == len(SLOW_CYCLE_STATIC_ENDPOINTS) + len(SERVICE_ENDPOINTS)


def test_service_definitions_are_unique() -> None:
    """Ключи сервисов уникальны, а SSH и SFTP используют один эндпоинт."""
    assert len(SERVICE_KEYS) == len(set(SERVICE_KEYS))
    assert SERVICE_KEYS == (
        "smb",
        "nfs",
        "ftp",
        "webdav",
        "ssh",
        "sftp",
        "rsync",
        "snmp",
        "tftp",
    )
    ssh = next(item for item in SERVICE_DEFINITIONS if item.key == "ssh")
    sftp = next(item for item in SERVICE_DEFINITIONS if item.key == "sftp")
    assert ssh.endpoint == sftp.endpoint
    assert len(SERVICE_ENDPOINTS) == 8
