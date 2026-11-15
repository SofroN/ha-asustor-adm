"""Настройка и переавторизация интеграции ASUSTOR NAS (ADM)."""

from __future__ import annotations

import logging
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
    except ADMError:
        _LOGGER.exception("Unexpected error while probing ASUSTOR NAS")
        return "unknown", SysInfo()
    finally:
        await session.close()
    return None, parse_sysinfo(payload)


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
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
                    vol.Required(CONF_USE_SSL, default=DEFAULT_USE_SSL): bool,
                    vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

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
