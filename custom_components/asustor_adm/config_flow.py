"""Настройка и переавторизация интеграции ASUSTOR NAS (ADM)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ADMClient
from .const import (
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SLOW_INTERVAL,
    CONF_USE_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SLOW_INTERVAL,
    DEFAULT_USE_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    END_SYSINFO,
    MAX_INTERVAL,
    MIN_INTERVAL,
)
from .exceptions import (
    ADMAuthError,
    ADMConnectionError,
    ADMError,
    ADMPermissionError,
    ADMTwoFactorRequiredError,
)
from .models import SysInfo
from .parse import parse_sysinfo

_LOGGER = logging.getLogger(__name__)


async def _async_probe(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[str | None, SysInfo]:
    """Проверить подключение и вернуть ошибку либо сведения об устройстве."""
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    client = ADMClient(
        session,
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        account=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        use_ssl=data.get(CONF_USE_SSL, DEFAULT_USE_SSL),
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    try:
        await client.async_login()
        payload = await client.async_request(END_SYSINFO)
    except ADMTwoFactorRequiredError:
        return "two_factor", SysInfo()
    except ADMAuthError:
        return "invalid_auth", SysInfo()
    except ADMConnectionError:
        return "cannot_connect", SysInfo()
    except ADMError as err:
        is_admin = bool(client.login and client.login.is_admin)
        if isinstance(err, ADMPermissionError) or not is_admin:
            # Тело отказа по правам неотличимо от тела истёкшей сессии,
            # поэтому причину подтверждает флаг прав из ответа авторизации.
            _LOGGER.debug(
                "Probe read denied by %s: %s, code %s, message %s, admin flag %s",
                END_SYSINFO.path,
                type(err).__name__,
                getattr(err, "code", None),
                getattr(err, "message", None),
                is_admin,
            )
            return "insufficient_privileges", SysInfo()
        _LOGGER.exception("Unexpected error while probing ASUSTOR NAS")
        return "unknown", SysInfo()
    finally:
        await session.close()
    return None, parse_sysinfo(payload)


def _connection_field(key: str, default: Any = None) -> vol.Marker:
    """Вернуть обязательное поле схемы, подставив значение по умолчанию."""
    if default is None:
        return vol.Required(key)
    return vol.Required(key, default=default)


def _connection_schema(current: Mapping[str, Any] | None = None) -> vol.Schema:
    """Построить схему полей подключения.

    Значения из ``current`` становятся значениями по умолчанию: так форма
    перенастройки предзаполнена данными записи. Пароль не подставляется —
    запись обновляется только после успешной проверки подключения.
    """
    values = current or {}
    return vol.Schema(
        {
            _connection_field(CONF_HOST, values.get(CONF_HOST)): str,
            _connection_field(CONF_PORT, values.get(CONF_PORT, DEFAULT_PORT)): cv.port,
            _connection_field(
                CONF_USE_SSL, values.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            ): bool,
            _connection_field(
                CONF_VERIFY_SSL, values.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ): bool,
            _connection_field(CONF_USERNAME, values.get(CONF_USERNAME)): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


def _is_identification_upgrade(entry: ConfigEntry, system: SysInfo) -> bool:
    """Сказать, уточняет ли серийный номер прежний идентификатор-адрес."""
    return system.serial is not None and entry.unique_id == entry.data.get(CONF_HOST)


class AsustorAdmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Поток настройки подключения к NAS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Запросить адрес, учётные данные и параметры TLS."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error, system = await _async_probe(self.hass, user_input)
            if error is not None:
                errors["base"] = error
            else:
                unique_id = system.serial or user_input[CONF_HOST]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=system.model or user_input[CONF_HOST],
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Изменить параметры подключения существующей записи."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error, system = await _async_probe(self.hass, user_input)
            if error is not None:
                errors["base"] = error
            else:
                return await self._async_apply_reconfigure(entry, user_input, system)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    async def _async_apply_reconfigure(
        self, entry: ConfigEntry, user_input: dict[str, Any], system: SysInfo
    ) -> ConfigFlowResult:
        """Обновить данные записи, сохранив привязку к тому же NAS."""
        candidate = system.serial or user_input[CONF_HOST]
        await self.async_set_unique_id(candidate)
        unique_id: str | None = None
        if candidate != entry.unique_id:
            if _is_identification_upgrade(entry, system):
                # Прежним идентификатором был адрес: новый серийный номер
                # принимается, только если он не занят другой записью.
                self._abort_if_unique_id_configured()
                unique_id = candidate
            else:
                self._abort_if_unique_id_mismatch(reason="wrong_device")
        updates: dict[str, Any] = {"data": user_input}
        if unique_id is not None:
            updates["unique_id"] = unique_id
        if system.model is not None:
            updates["title"] = system.model
        return self.async_update_reload_and_abort(entry, **updates)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Начать переавторизацию существующей записи."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Запросить пароль заново после истечения сессии."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_entry_missing")
        if user_input is not None:
            data = {**entry.data, **user_input}
            error, _ = await _async_probe(self.hass, data)
            if error is not None:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Вернуть поток настроек интервалов опроса."""
        return AsustorAdmOptionsFlow()


class AsustorAdmOptionsFlow(OptionsFlow):
    """Настройки интервалов быстрого и медленного опроса."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Запросить интервалы опроса."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FAST_INTERVAL,
                        default=options.get(CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL),
                    ): vol.All(
                        cv.positive_int, vol.Range(min=MIN_INTERVAL, max=MAX_INTERVAL)
                    ),
                    vol.Required(
                        CONF_SLOW_INTERVAL,
                        default=options.get(CONF_SLOW_INTERVAL, DEFAULT_SLOW_INTERVAL),
                    ): vol.All(
                        cv.positive_int, vol.Range(min=MIN_INTERVAL, max=MAX_INTERVAL)
                    ),
                }
            ),
        )
