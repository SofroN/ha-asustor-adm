"""Константы интеграции ASUSTOR ADM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DOMAIN: Final = "asustor_adm"
MANUFACTURER: Final = "ASUSTOR"
DEVICE_NAME: Final = "ASUSTOR NAS (ADM)"

DEFAULT_PORT: Final = 8001
DEFAULT_USE_SSL: Final = True
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_FAST_INTERVAL: Final = 60
DEFAULT_SLOW_INTERVAL: Final = 300
MIN_INTERVAL: Final = 15
MAX_INTERVAL: Final = 3600

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USE_SSL: Final = "use_ssl"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_FAST_INTERVAL: Final = "fast_interval"
CONF_SLOW_INTERVAL: Final = "slow_interval"

API_ROOT: Final = "/portal/apis"

REQUEST_TIMEOUT: Final = 10
LOGIN_TIMEOUT: Final = 5

ERR_NONE: Final = 0
#: Сессия ADM недействительна или истекла — единственный код, требующий повторной авторизации.
ERR_SESSION_INVALID: Final = 5000
#: Нет связи с сервером обновлений ASUSTOR (проверка обновлений невозможна).
ERR_UPDATE_CANNOT_CONNECT: Final = 5005
#: Установлена последняя версия ADM — новее нет.
ERR_UPDATE_LATEST: Final = 6209
#: Предлагаемая версия совпадает с установленной.
ERR_UPDATE_SAME_VERSION: Final = 6215
#: Учётной записи требуется одноразовый код двухфакторной авторизации.
ERR_TWO_STEP_REQUIRED: Final = 5034
#: Устройство отклонило запрос.
ERR_DEVICE_REJECTED: Final = 6300

ERROR_CODES: Final = frozenset(
    {
        ERR_SESSION_INVALID,
        ERR_TWO_STEP_REQUIRED,
        ERR_UPDATE_CANNOT_CONNECT,
        ERR_UPDATE_LATEST,
        ERR_UPDATE_SAME_VERSION,
        ERR_DEVICE_REJECTED,
    }
)

#: Коды, которыми ADM сообщает об отказе в доступе. Код 6300 приходит с текстом
#: `operation not permitted`, когда чтение запрещено правами учётной записи.
PERMISSION_DENIED_CODES: Final = frozenset({ERR_DEVICE_REJECTED})

HTTP_METHOD_POST: Final = "post"
HTTP_METHOD_GET: Final = "get"


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Эндпоинт API ADM: путь собирается из модуля и имени CGI.

    ``params`` — параметры запроса, которых требует контракт ADM: без них
    устройство отвечает кодом 5302 и сведений не отдаёт.
    """

    module: str
    name: str
    act: str | None = None
    params: tuple[tuple[str, str], ...] = ()

    @property
    def path(self) -> str:
        """Вернуть путь эндпоинта без параметров."""
        if self.module:
            return f"{API_ROOT}/{self.module}/{self.name}"
        return f"{API_ROOT}/{self.name}"


END_LOGIN: Final = Endpoint("", "login.cgi", "login")
END_ACTIVITY: Final = Endpoint("activityMonitor", "act.cgi", "list")
END_SYSINFO: Final = Endpoint("information", "sysinfo.cgi", "sys")
END_VOLUME_LIST: Final = Endpoint("storageManager", "volume.cgi", "list")
END_VOLUME_GET: Final = Endpoint("storageManager", "volume.cgi", "get")
END_DISK_LIST: Final = Endpoint("storageManager", "disk_smart.cgi", "list")
END_DISK_SMART: Final = Endpoint("storageManager", "disk_smart.cgi", "smart")
END_SYSINFO_NET: Final = Endpoint("information", "sysinfo.cgi", "net")
END_SYSINFO_WAN: Final = Endpoint("information", "sysinfo.cgi", "wan")
#: Без параметров постраничности `onlineuser.cgi` отвечает кодом 5302.
SESSIONS_PAGING: Final = (
    ("sort", "0"),
    ("ascend", "0"),
    ("start", "0"),
    ("limit", "100"),
)
END_SESSIONS: Final = Endpoint("information", "onlineuser.cgi", "list", SESSIONS_PAGING)
END_EXT_DISK: Final = Endpoint("external", "extdisk.cgi", "list")
END_TASKS: Final = Endpoint("taskmonitor", "taskmonitor.cgi", "task_list")
END_FIRMWARE: Final = Endpoint("settings", "firmwarestatus.cgi", "get_static_info")
END_APP_UPDATES: Final = Endpoint("appCentral", "appcentral.cgi", "count")
END_POWER: Final = Endpoint("", "admin.cgi")

#: Запросы быстрого цикла опроса.
FAST_CYCLE_ENDPOINTS: Final = (
    END_ACTIVITY,
    END_SYSINFO,
    END_VOLUME_LIST,
    END_DISK_LIST,
)

#: Запросы медленного цикла опроса, не зависящие от состава устройства.
SLOW_CYCLE_STATIC_ENDPOINTS: Final = (
    END_SYSINFO_NET,
    END_SYSINFO_WAN,
    END_SESSIONS,
    END_EXT_DISK,
    END_TASKS,
    END_FIRMWARE,
    END_APP_UPDATES,
)


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """Описание сетевого сервиса NAS и поля ответа с признаком включения."""

    key: str
    endpoint: Endpoint
    field: str


#: Часть модулей отдаёт настройки только вместе с параметром `tab`: без него
#: ADM отвечает кодом 5302 с текстом `tab`, и сведений о сервисе не получить.
SERVICE_DEFINITIONS: Final = (
    ServiceDefinition(
        "smb", Endpoint("services", "windows.cgi", "get", (("tab", "cifs"),)), "enable"
    ),
    ServiceDefinition(
        "nfs",
        Endpoint("services", "nfs.cgi", "get", (("tab", "Nfs_Get_Enable"),)),
        "IsEnabled",
    ),
    ServiceDefinition(
        "ftp",
        Endpoint("services", "ftp.cgi", "get", (("tab", "general"),)),
        "enable",
    ),
    ServiceDefinition(
        "webdav",
        Endpoint("services", "http.cgi", "get", (("tab", "webdav"),)),
        "webdav_enable",
    ),
    ServiceDefinition("ssh", Endpoint("services", "terminal.cgi", "get"), "ssh_enable"),
    ServiceDefinition(
        "sftp", Endpoint("services", "terminal.cgi", "get"), "sftp_enable"
    ),
    ServiceDefinition(
        "rsync", Endpoint("services", "rsync.cgi", "get_sets"), "rsync_enable"
    ),
    ServiceDefinition(
        "snmp",
        Endpoint("services", "snmp.cgi", "get", (("tab", "Get"),)),
        "enable_snmp",
    ),
    ServiceDefinition(
        "tftp", Endpoint("services", "tftp_server.cgi", "get"), "enabled"
    ),
)

SERVICE_KEYS: Final = tuple(definition.key for definition in SERVICE_DEFINITIONS)

#: Уникальные эндпоинты сервисов: SSH и SFTP приходят из одного ответа.
SERVICE_ENDPOINTS: Final = tuple(
    dict.fromkeys(definition.endpoint for definition in SERVICE_DEFINITIONS)
)

#: Коды проверки обновлений, означающие «новее нет»: не сбой, а подтверждённый ответ.
#: Коды контекстны для каждого CGI: 5005 у `volume.cgi` значит «нет такого тома».
UPDATE_UP_TO_DATE_CODES: Final = frozenset({ERR_UPDATE_LATEST, ERR_UPDATE_SAME_VERSION})

POWER_SHUTDOWN: Final = "shutdown"
POWER_RESTART: Final = "restart"
POWER_SUSPEND: Final = "suspend"
