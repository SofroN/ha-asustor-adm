"""Клиент внутреннего HTTP API ASUSTOR ADM."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode

import aiohttp

from .const import (
    END_LOGIN,
    END_POWER,
    ERR_NONE,
    ERR_SESSION_INVALID,
    HTTP_METHOD_GET,
    HTTP_METHOD_POST,
    LOGIN_TIMEOUT,
    POWER_RESTART,
    POWER_SHUTDOWN,
    POWER_SUSPEND,
    REQUEST_TIMEOUT,
    Endpoint,
)
from .exceptions import (
    ADMAuthError,
    ADMConnectionError,
    ADMPowerError,
    ADMResponseError,
    ADMSessionExpiredError,
    ADMTwoFactorRequiredError,
)
from .values import to_flag, to_text

_LOGGER = logging.getLogger(__name__)

_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"
_TWO_FACTOR_HINTS: Final = ("two-step", "two_step", "twostep", "otp", "verify")
_POWER_ACTIONS: Final = {
    POWER_SHUTDOWN: POWER_SHUTDOWN,
    POWER_RESTART: POWER_RESTART,
    POWER_SUSPEND: POWER_SUSPEND,
}


@dataclass(frozen=True, slots=True)
class ADMLogin:
    """Результат авторизации и флаги возможностей устройства."""

    sid: str
    is_admin: bool = False
    can_suspend: bool = False
    can_wol: bool = False
    chassis: str | None = None


def check_envelope(payload: Mapping[str, Any]) -> None:
    """Проверить конверт ответа ADM и поднять типизированную ошибку.

    Успехом считается только явный ``success: true``. Ответ без признака
    успеха, но с ненулевым кодом ошибки, тоже считается неуспешным. Ответ
    без обоих полей — полезные данные (так отвечает, например,
    `firmwarestatus.cgi?act=get_static_info`).
    """
    error_code = payload.get("error_code")
    if isinstance(error_code, str):
        error_code = int(error_code) if error_code.isdigit() else None
    if payload.get("success") is True:
        return
    message = to_text(payload.get("error_msg"))
    if "success" in payload:
        if error_code == ERR_SESSION_INVALID:
            raise ADMSessionExpiredError
        raise ADMResponseError(error_code, message)
    if error_code not in (None, ERR_NONE):
        if error_code == ERR_SESSION_INVALID:
            raise ADMSessionExpiredError
        raise ADMResponseError(error_code, message)


def _decode(text: str) -> dict[str, Any]:
    """Разобрать тело ответа как JSON-объект."""
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except ValueError as err:
        raise ADMResponseError(None, "response is not valid JSON") from err
    if not isinstance(payload, dict):
        raise ADMResponseError(None, "response is not a JSON object")
    return payload


class ADMClient:
    """Клиент ADM API: одна сессия, общая для всех координаторов."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        host: str,
        port: int,
        account: str,
        password: str,
        use_ssl: bool = True,
        verify_ssl: bool = True,
    ) -> None:
        """Создать клиент для NAS по указанному адресу."""
        self._session = session
        self._base_url = f"{'https' if use_ssl else 'http'}://{host}:{port}"
        self._account = account
        self._password = password
        self._ssl_kwargs: dict[str, Any] = {} if verify_ssl else {"ssl": False}
        self._login: ADMLogin | None = None

    @property
    def login(self) -> ADMLogin | None:
        """Вернуть результат последней успешной авторизации."""
        return self._login

    @property
    def sid(self) -> str | None:
        """Вернуть идентификатор сессии."""
        return self._login.sid if self._login else None

    async def async_login(self) -> ADMLogin:
        """Авторизоваться и сохранить флаги возможностей устройства."""
        form = {"account": self._account, "password": self._password, "stay": "yes"}
        try:
            payload = await self._async_send(
                END_LOGIN, form=form, timeout=LOGIN_TIMEOUT, with_sid=False
            )
        except ADMResponseError as err:
            raise ADMAuthError(f"login rejected with code {err.code}") from err
        if payload.get("success") is not True:
            if any(
                key.startswith(hint) for key in payload for hint in _TWO_FACTOR_HINTS
            ):
                raise ADMTwoFactorRequiredError
            raise ADMAuthError("login rejected")
        sid = to_text(payload.get("sid"))
        if sid is None:
            raise ADMAuthError("login response has no session id")
        self._login = ADMLogin(
            sid=sid,
            is_admin=bool(to_flag(payload.get("isadministrators"))),
            can_suspend=bool(to_flag(payload.get("cansuspend"))),
            can_wol=bool(to_flag(payload.get("canwol"))),
            chassis=to_text(payload.get("chassis")),
        )
        return self._login

    async def async_request(
        self,
        endpoint: Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = HTTP_METHOD_POST,
        form: Mapping[str, Any] | None = None,
        _retry: bool = True,
    ) -> dict[str, Any]:
        """Выполнить запрос с одной повторной авторизацией по коду 5000."""
        if self._login is None:
            await self.async_login()
        try:
            return await self._async_send(
                endpoint, params=params, method=method, form=form
            )
        except ADMSessionExpiredError:
            if not _retry:
                raise
            _LOGGER.debug(
                "Session expired for %s, re-authenticating once", endpoint.path
            )
            await self.async_login()
            return await self.async_request(
                endpoint, params=params, method=method, form=form, _retry=False
            )

    async def async_close(self) -> None:
        """Закрыть HTTP-сессию клиента."""
        await self._session.close()

    async def async_power(self, action: str) -> None:
        """Отправить команду управления питанием."""
        if action not in _POWER_ACTIONS:
            raise ADMPowerError(f"unsupported action {action}")
        try:
            await self._async_send(
                END_POWER,
                params={"act": _POWER_ACTIONS[action]},
                method=HTTP_METHOD_GET,
            )
        except ADMResponseError as err:
            raise ADMPowerError(str(err)) from err

    async def _async_send(
        self,
        endpoint: Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = HTTP_METHOD_POST,
        form: Mapping[str, Any] | None = None,
        timeout: int = REQUEST_TIMEOUT,
        with_sid: bool = True,
    ) -> dict[str, Any]:
        """Выполнить один HTTP-запрос и проверить конверт ответа."""
        query: dict[str, str] = {}
        if endpoint.act is not None:
            query["act"] = endpoint.act
        if with_sid and self._login is not None:
            query["sid"] = self._login.sid
        if params:
            query.update({key: str(value) for key, value in params.items()})

        body: bytes | None = None
        if form is not None:
            body = urlencode(form).encode()
        elif method == HTTP_METHOD_POST:
            body = b""

        try:
            async with self._session.request(
                method.upper(),
                f"{self._base_url}{endpoint.path}",
                params=query,
                data=body,
                headers={"Content-Type": _CONTENT_TYPE},
                timeout=aiohttp.ClientTimeout(total=timeout),
                **self._ssl_kwargs,
            ) as response:
                response.raise_for_status()
                text = await response.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise ADMConnectionError(str(err)) from err

        payload = _decode(text)
        if with_sid:
            check_envelope(payload)
        return payload
