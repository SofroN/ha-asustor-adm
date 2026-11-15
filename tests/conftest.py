"""Общие приспособления тестов интеграции ASUSTOR ADM."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from helpers import default_routes, load_fixture
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.asustor_adm.api import ADMLogin, check_envelope
from custom_components.asustor_adm.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USE_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    END_ACTIVITY,
    END_APP_UPDATES,
    END_DISK_LIST,
    END_DISK_SMART,
    END_EXT_DISK,
    END_FIRMWARE,
    END_SESSIONS,
    END_SYSINFO,
    END_TASKS,
    END_VOLUME_GET,
    END_VOLUME_LIST,
    ERR_TWO_STEP_REQUIRED,
    SERVICE_DEFINITIONS,
)
from custom_components.asustor_adm.exceptions import (
    ADMAuthError,
    ADMConnectionError,
    ADMResponseError,
    ADMTwoFactorRequiredError,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Iterator[None]:
    """Включить загрузку сторонних интеграций во всех тестах."""
    yield


class FakeADMClient:
    """Подменённый клиент ADM с настраиваемыми ответами."""

    def __init__(self) -> None:
        """Подготовить клиент с ответами по умолчанию."""
        self.routes: dict[tuple[str, str | None], dict[str, Any]] = default_routes()
        self.routes_by_params: dict[tuple[str, str, Any], dict[str, Any]] = {
            (END_VOLUME_GET.path, "vid", 1): load_fixture("volume_1"),
            (END_VOLUME_GET.path, "vid", 2): load_fixture("volume_2"),
        }
        self.requests: list[tuple[str, str | None]] = []
        self.params: list[dict[str, Any] | None] = []
        self.power_actions: list[str] = []
        self.failing_paths: set[str] = set()
        self.failing_params: dict[str, set[Any]] = {}
        #: Заданные ответные ошибки по пути эндпоинта; остальные маршруты не меняются.
        self.error_paths: dict[str, Exception] = {}
        self.login_payload: dict[str, Any] = load_fixture("login")
        self.login_calls = 0
        self.fail_login: Exception | None = None
        self.fail_power: Exception | None = None
        self.auth_error_paths: set[str] = set()

    def route(self, name: str) -> None:
        """Заменить ответ эндпоинта фикстурой по имени."""
        self.routes.update(_named_route(name))

    def set_route(self, endpoint: Any, payload: dict[str, Any]) -> None:
        """Задать ответ конкретного эндпоинта."""
        self.routes[(endpoint.path, endpoint.act)] = payload

    def set_route_by_params(
        self, endpoint: Any, key: str, value: Any, payload: dict[str, Any]
    ) -> None:
        """Задать ответ эндпоинта для конкретного значения параметра."""
        self.routes_by_params[(endpoint.path, key, value)] = payload

    @property
    def login(self) -> ADMLogin | None:
        """Вернуть сведения авторизации, как у настоящего клиента."""
        return self._login

    @property
    def sid(self) -> str | None:
        """Вернуть идентификатор сессии."""
        return self._login.sid if self._login else None

    async def async_login(self) -> ADMLogin:
        """Выполнить подменённую авторизацию."""
        self.login_calls += 1
        if self.fail_login is not None:
            raise self.fail_login
        if self.login_payload.get("success") is not True:
            if self.login_payload.get("error_code") == ERR_TWO_STEP_REQUIRED:
                raise ADMTwoFactorRequiredError
            raise ADMAuthError("login rejected")
        self._login = ADMLogin(
            sid="TEST-SID",
            is_admin=bool(self.login_payload.get("isadministrators")),
            can_suspend=bool(self.login_payload.get("cansuspend")),
            can_wol=bool(self.login_payload.get("canwol", True)),
            chassis=self.login_payload.get("chassis"),
        )
        return self._login

    async def async_request(
        self,
        endpoint: Any,
        *,
        params: Any = None,
        method: str = "post",
        form: Any = None,
        _retry: bool = True,
    ) -> dict[str, Any]:
        """Вернуть записанный ответ или сымитировать сбой."""
        self.requests.append((endpoint.path, endpoint.act))
        self.params.append(dict(params) if params else None)
        if endpoint.path in self.error_paths:
            raise self.error_paths[endpoint.path]
        if endpoint.path in self.auth_error_paths:
            raise ADMAuthError("fake auth error")
        if endpoint.path in self.failing_paths:
            raise ADMConnectionError("fake connection error")
        blocked = self.failing_params.get(endpoint.path, set())
        if params and params.get("vid") in blocked:
            raise ADMConnectionError("fake connection error")
        payload = self.routes_by_params.get(
            (endpoint.path, "vid", (params or {}).get("vid"))
        )
        if payload is None:
            payload = self.routes.get((endpoint.path, endpoint.act))
        if payload is None:
            raise ADMResponseError(6300, "route is not configured")
        check_envelope(payload)
        return payload

    async def async_power(self, action: str) -> None:
        """Записать команду питания или сымитировать отказ."""
        if self.fail_power is not None:
            raise self.fail_power
        self.power_actions.append(action)

    async def async_close(self) -> None:
        """Ничего не закрывать."""


def _named_route(name: str) -> dict[tuple[str, str | None], dict[str, Any]]:
    """Собрать маршрут из имени фикстуры и известных эндпоинтов."""
    known = {
        "activity": END_ACTIVITY,
        "sysinfo": END_SYSINFO,
        "volumes": END_VOLUME_LIST,
        "volume_1": END_VOLUME_GET,
        "disks": END_DISK_LIST,
        "smart": END_DISK_SMART,
        "sessions": END_SESSIONS,
        "tasks": END_TASKS,
        "extdisks": END_EXT_DISK,
        "firmware": END_FIRMWARE,
        "appcentral": END_APP_UPDATES,
        "service_smb": SERVICE_DEFINITIONS[0].endpoint,
        "service_nfs": SERVICE_DEFINITIONS[1].endpoint,
        "service_ftp": SERVICE_DEFINITIONS[2].endpoint,
        "service_webdav": SERVICE_DEFINITIONS[3].endpoint,
        "service_terminal": SERVICE_DEFINITIONS[4].endpoint,
        "service_rsync": SERVICE_DEFINITIONS[6].endpoint,
        "service_snmp": SERVICE_DEFINITIONS[7].endpoint,
        "service_tftp": SERVICE_DEFINITIONS[8].endpoint,
    }
    if name not in known:
        raise KeyError(f"unknown fixture route {name}")
    endpoint = known[name]
    return {(endpoint.path, endpoint.act): load_fixture(name)}


@pytest.fixture(name="adm")
def adm_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeADMClient]:
    """Подменить клиент ADM в интеграции и в потоке настройки."""
    client = FakeADMClient()

    def _factory(*args: Any, **kwargs: Any) -> FakeADMClient:
        return client

    monkeypatch.setattr("custom_components.asustor_adm.ADMClient", _factory)
    monkeypatch.setattr("custom_components.asustor_adm.config_flow.ADMClient", _factory)
    yield client


@pytest.fixture(name="entry")
def entry_fixture(hass: Any) -> MockConfigEntry:
    """Создать запись интеграции с настройками по умолчанию."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AS3304T",
        unique_id="SN012345678",
        data={
            CONF_HOST: "nas.example.com",
            CONF_PORT: 8001,
            CONF_USE_SSL: True,
            CONF_VERIFY_SSL: False,
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry
