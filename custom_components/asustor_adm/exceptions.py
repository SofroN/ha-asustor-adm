"""Типизированные исключения клиента ADM API."""

from __future__ import annotations


class ADMError(Exception):
    """Базовая ошибка интеграции."""


class ADMConnectionError(ADMError):
    """Соединение с NAS невозможно: сеть, TLS или тайм-аут."""


class ADMResponseError(ADMError):
    """ADM вернул неуспешный ответ с прикладным кодом ошибки."""

    def __init__(self, code: int | None, message: str | None = None) -> None:
        """Сохранить код и текст ошибки ADM."""
        self.code = code
        self.message = message
        super().__init__(f"ADM error {code}: {message or 'no message'}")


class ADMPermissionError(ADMResponseError):
    """ADM отклонил запрос из-за недостатка прав учётной записи.

    Наследуется от :class:`ADMResponseError`, чтобы существующие обработчики
    неуспешного ответа (код ошибки, деградация цикла) продолжали работать.
    """


class ADMSessionExpiredError(ADMError):
    """Сессия ADM недействительна (код 5000)."""


class ADMAuthError(ADMError):
    """Авторизация отклонена: неверные учётные данные."""


class ADMTwoFactorRequiredError(ADMAuthError):
    """Для учётной записи требуется двухфакторная авторизация."""


class ADMPowerError(ADMError):
    """Команда управления питанием не принята NAS."""
