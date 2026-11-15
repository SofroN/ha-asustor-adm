"""Клиент ADM API: транспорт, конверт ошибок, авторизация (задачи 2.1-2.3)."""

from __future__ import annotations

import contextlib
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from helpers import load_fixture

from custom_components.asustor_adm.api import ADMClient, check_envelope
from custom_components.asustor_adm.const import END_ACTIVITY, END_LOGIN, END_POWER
from custom_components.asustor_adm.exceptions import (
    ADMAuthError,
    ADMConnectionError,
    ADMResponseError,
    ADMSessionExpiredError,
    ADMTwoFactorRequiredError,
)

LOGIN_OK = {
    "success": True,
    "sid": "SID-1",
    "isadministrators": True,
    "cansuspend": False,
}


class FakeResponse:
    """Минимальная заглушка ответа aiohttp."""

    def __init__(
        self, payload: Any = None, *, status: int = 200, text: str | None = None
    ):
        """Подготовить ответ из объекта или готового текста."""
        self.status = status
        self._text = text if text is not None else _dumps(payload)

    def raise_for_status(self) -> None:
        """Сымитировать проверку HTTP-статуса."""
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=self.status
            )

    async def text(self) -> str:
        """Вернуть тело ответа."""
        return self._text

    async def __aenter__(self) -> FakeResponse:
        """Войти в контекст ответа."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Выйти из контекста ответа."""


def _dumps(payload: Any) -> str:
    import json

    return json.dumps(payload)


class FakeSession:
    """Подменённая HTTP-сессия с заранее заданными ответами."""

    def __init__(self, payloads: list[Any], *, error: Exception | None = None):
        """Подготовить очередь ответов."""
        self._payloads = list(payloads)
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Записать вызов и вернуть следующий ответ."""
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._error is not None:
            raise self._error
        payload = self._payloads.pop(0) if self._payloads else {"success": True}
        if isinstance(payload, FakeResponse):
            return payload
        return FakeResponse(payload)


def _client(session: FakeSession) -> ADMClient:
    return ADMClient(
        session, host="nas.example.com", port=8001, account="admin", password="pw"
    )


async def test_request_uses_form_template_empty_body_and_no_cache_buster() -> None:
    """Запрос уходит POST-ом с пустым телом, `sid` в query и без `_dc`."""
    session = FakeSession([LOGIN_OK, load_fixture("activity")])
    client = _client(session)
    await client.async_login()
    await client.async_request(END_ACTIVITY)

    login_call, activity_call = session.calls
    assert login_call["method"] == "POST"
    assert b"account=admin" in login_call["data"]
    assert activity_call["method"] == "POST"
    assert activity_call["data"] == b""
    assert activity_call["params"] == {"act": "list", "sid": "SID-1"}
    assert "_dc" not in activity_call["params"]
    assert "_dc" not in activity_call["url"]


async def test_real_transport_sends_content_length_zero(
    aiohttp_server: Any, request: pytest.FixtureRequest
) -> None:
    """Настоящий HTTP-сервер видит `Content-Length: 0` и `sid` в query."""
    with contextlib.suppress(pytest.FixtureLookupError):
        request.getfixturevalue("socket_enabled")
    seen: list[web.Request] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(request)
        return web.json_response({"success": True, "sid": "SID-1"})

    app = web.Application()
    app.router.add_route("*", "/portal/apis/{tail:.*}", handler)
    server = await aiohttp_server(app)

    session = aiohttp.ClientSession()
    client = ADMClient(
        session,
        host=server.host,
        port=server.port,
        account="admin",
        password="pw",
        use_ssl=False,
    )
    try:
        await client.async_login()
        await client.async_request(END_ACTIVITY)
    finally:
        await session.close()

    assert len(seen) == 2
    assert seen[1].headers["Content-Length"] == "0"
    assert seen[1].query["act"] == "list"
    assert seen[1].query["sid"] == "SID-1"
    assert "_dc" not in seen[1].query


async def test_session_expired_is_followed_by_single_retry() -> None:
    """Код 5000 приводит ровно к одной повторной авторизации и одному повтору."""
    expired = load_fixture("error_session_expired")
    session = FakeSession([LOGIN_OK, expired, LOGIN_OK, load_fixture("activity")])
    client = _client(session)

    payload = await client.async_request(END_ACTIVITY)

    assert payload["cpucount"] == 4
    assert len(session.calls) == 4
    assert session.calls[0]["url"].endswith(END_LOGIN.path)
    assert session.calls[2]["url"].endswith(END_LOGIN.path)


async def test_repeated_expiration_is_not_retried_twice() -> None:
    """Повторный код 5000 после переавторизации не запускает новый цикл."""
    expired = load_fixture("error_session_expired")
    session = FakeSession([LOGIN_OK, expired, LOGIN_OK, expired])
    client = _client(session)

    with pytest.raises(ADMSessionExpiredError):
        await client.async_request(END_ACTIVITY)

    assert len(session.calls) == 4


async def test_business_error_is_not_retried() -> None:
    """Прикладная ошибка не приводит к повторной авторизации."""
    failure = load_fixture("error_business")
    session = FakeSession([LOGIN_OK, failure])
    client = _client(session)

    with pytest.raises(ADMResponseError) as err:
        await client.async_request(END_ACTIVITY)

    assert err.value.code == 6300
    assert len(session.calls) == 2


async def test_error_code_without_success_is_failure() -> None:
    """Ответ только с кодом ошибки считается неуспешным."""
    session = FakeSession([LOGIN_OK, load_fixture("error_code_only")])
    client = _client(session)

    with pytest.raises(ADMResponseError) as err:
        await client.async_request(END_ACTIVITY)

    assert err.value.code == 6209


async def test_payload_without_envelope_is_returned() -> None:
    """Ответ без признака успеха и без кода ошибки считается данными."""
    session = FakeSession([LOGIN_OK, load_fixture("firmware")])
    client = _client(session)

    payload = await client.async_request(END_ACTIVITY)

    assert payload["installed_version"] == "5.1.4.RM62"


async def test_failed_reauth_stops_further_attempts() -> None:
    """Ошибка авторизации при переавторизации не даёт новых запросов."""
    session = FakeSession(
        [LOGIN_OK, load_fixture("error_session_expired"), {"success": False}]
    )
    client = _client(session)

    with pytest.raises(ADMAuthError):
        await client.async_request(END_ACTIVITY)

    assert len(session.calls) == 3


async def test_invalid_json_raises_response_error() -> None:
    """Ответ, который не удаётся разобрать, даёт ошибку ответа."""
    session = FakeSession([LOGIN_OK, FakeResponse(text="<h1>411 Length Required</h1>")])
    client = _client(session)

    with pytest.raises(ADMResponseError) as err:
        await client.async_request(END_ACTIVITY)

    assert err.value.code is None


async def test_two_factor_login_is_reported() -> None:
    """Ответ с признаком двухфакторной авторизации даёт отдельную ошибку."""
    session = FakeSession([load_fixture("login_two_factor")])
    client = _client(session)

    with pytest.raises(ADMTwoFactorRequiredError):
        await client.async_login()


async def test_connection_error_is_mapped() -> None:
    """Сетевой сбой превращается в ошибку соединения."""
    session = FakeSession([LOGIN_OK], error=aiohttp.ClientConnectionError("boom"))
    client = _client(session)

    with pytest.raises(ADMConnectionError):
        await client.async_login()


async def test_power_command_uses_get_with_action() -> None:
    """Команда питания отправляется GET-запросом к admin.cgi."""
    session = FakeSession([LOGIN_OK, load_fixture("success_empty")])
    client = _client(session)
    await client.async_login()

    await client.async_power("shutdown")

    call = session.calls[-1]
    assert call["method"] == "GET"
    assert call["url"].endswith(END_POWER.path)
    assert call["params"] == {"act": "shutdown", "sid": "SID-1"}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"success": True}, None),
        ({"success": True, "error_code": 0}, None),
        ({"installed_version": "5.1.4.RM62"}, None),
        ({"success": False, "error_code": 6300}, ADMResponseError),
        ({"success": False, "error_code": 5000}, ADMSessionExpiredError),
        ({"error_code": 6215}, ADMResponseError),
    ],
)
def test_check_envelope_forms(payload: dict[str, Any], expected: type | None) -> None:
    """Конверт ответа разбирается для всех наблюдаемых форм."""
    if expected is None:
        check_envelope(payload)
    else:
        with pytest.raises(expected):
            check_envelope(payload)
