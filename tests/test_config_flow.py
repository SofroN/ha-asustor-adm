"""Потоки настройки, настроек и переавторизации (задачи 3.1-3.3)."""

from __future__ import annotations

from datetime import timedelta

from helpers import load_fixture, setup_integration
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.asustor_adm.const import (
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SLOW_INTERVAL,
    CONF_USE_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    END_ACTIVITY,
)
from custom_components.asustor_adm.exceptions import ADMConnectionError

USER_INPUT = {
    CONF_HOST: "nas.example.com",
    CONF_PORT: 8001,
    CONF_USE_SSL: True,
    CONF_VERIFY_SSL: False,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
}


async def test_user_flow_creates_entry(hass, adm) -> None:
    """Успешная настройка создаёт запись с серийным номером как unique_id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "AS3304T"
    assert result["result"].unique_id == "SN012345678"


async def test_user_flow_rejects_invalid_auth(hass, adm) -> None:
    """Неверный пароль завершает настройку ошибкой авторизации."""
    adm.login_payload = {"success": False}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_user_flow_reports_unreachable_host(hass, adm) -> None:
    """Недоступный хост завершает настройку ошибкой соединения."""
    adm.fail_login = ADMConnectionError("no route to host")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_reports_two_factor(hass, adm) -> None:
    """Включённая 2FA даёт отдельную ошибку вместо тихого сбоя."""
    adm.login_payload = load_fixture("login_two_factor")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["errors"] == {"base": "two_factor"}


async def test_options_flow_applies_new_interval(hass, adm, entry) -> None:
    """Новый интервал применяется к существующей записи без перезапуска."""
    await setup_integration(hass, entry)
    assert entry.runtime_data.fast.update_interval == timedelta(seconds=60)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FAST_INTERVAL: 120, CONF_SLOW_INTERVAL: 900}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_FAST_INTERVAL: 120, CONF_SLOW_INTERVAL: 900}
    assert entry.runtime_data.fast.update_interval == timedelta(seconds=120)
    assert entry.runtime_data.slow.update_interval == timedelta(seconds=900)


async def test_reauth_flow_restores_entry(hass, adm, entry) -> None:
    """Истёкшая сессия ведёт к запросу пароля и восстановлению записи."""
    await setup_integration(hass, entry)

    adm.auth_error_paths.add(END_ACTIVITY.path)
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    reauth = [flow for flow in flows if flow["context"].get("source") == "reauth"]
    assert reauth, "поток переавторизации не запущен"

    result = await hass.config_entries.flow.async_configure(
        reauth[0]["flow_id"], {CONF_PASSWORD: "new-secret"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-secret"
