"""Публикация релиза на GitHub или Forgejo вместе с архивом плагина.

Один запуск делает релиз атомарно: черновик → загрузка архива → публикация.
Пока архив не загружен, релиз остается черновиком и не виден пользователям,
поэтому сбой загрузки не оставляет «пустой» релиз: повторный запуск
дозагружает недостающее и публикует уже собранный черновик.

Хостинги различаются только загрузкой вложений: GitHub принимает двоичное тело
на ``uploads.github.com``, Forgejo — ``multipart/form-data`` с полем
``attachment``. Всё остальное совпадает, так как Forgejo повторяет API GitHub.

Две особенности self-hosted Forgejo учтены явно: адрес API выводится из адреса
сервера, если ``GITHUB_API_URL`` не задан, а самоподписанный сертификат не
обрывает публикацию — запрос повторяется без проверки TLS (сервер тот же, что
в ``GITHUB_SERVER_URL``; для GitHub такая поблажка не действует).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

HTTP_TIMEOUT_SECONDS: Final = 120
USER_AGENT: Final = "ha-asustor-adm-release"
ENGINE_GITHUB: Final = "github"
ENGINE_GITEA: Final = "gitea"
ENGINES: Final = (ENGINE_GITHUB, ENGINE_GITEA)


class ReleaseError(Exception):
    """Отказ API или некорректные входные данные публикации."""


@dataclass(frozen=True, slots=True)
class Response:
    """Ответ HTTP: статус и тело."""

    status: int
    body: bytes

    def json(self) -> Any:
        """Разобрать тело как JSON; неразбираемое тело — ошибка."""
        try:
            return json.loads(self.body or b"{}")
        except json.JSONDecodeError as error:
            raise ReleaseError(f"ответ не JSON: {error}") from error


class Transport(Protocol):
    """HTTP-транспорт: единственная точка подмены в тестах."""

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes | None,
    ) -> Response: ...


class UrllibTransport:
    """Транспорт на стандартной библиотеке: без внешних зависимостей.

    ``insecure`` отключает проверку сертификата сервера: так публикуется
    релиз на self-hosted Forgejo, сертификат которого не попал в доверенные
    на раннере. Для GitHub режим не включается.
    """

    def __init__(self, *, insecure: bool = False) -> None:
        self._insecure = insecure

    def _context(self) -> ssl.SSLContext | None:
        """Контекст TLS: строгий по умолчанию, без проверки — только явно."""
        if not self._insecure:
            return None
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes | None,
    ) -> Response:
        request = urllib.request.Request(
            url, data=data, headers=dict(headers), method=method
        )
        try:
            with urllib.request.urlopen(
                request, timeout=HTTP_TIMEOUT_SECONDS, context=self._context()
            ) as reply:
                return Response(status=reply.status, body=reply.read())
        except urllib.error.HTTPError as error:
            # Ошибка API — это данные: тело содержит причину отказа.
            return Response(status=error.code, body=error.read())
        except urllib.error.URLError as error:
            raise ReleaseError(f"нет связи с {url}: {error.reason}") from error


@dataclass(frozen=True, slots=True)
class Settings:
    """Параметры API: адрес, репозиторий, токен и движок."""

    api_url: str
    repository: str
    token: str
    engine: str


def detect_engine(api_url: str) -> str:
    """Определить движок по адресу API: GitHub или Forgejo/Gitea."""
    host = urllib.parse.urlsplit(api_url).hostname or ""
    return ENGINE_GITHUB if host == "api.github.com" else ENGINE_GITEA


def resolve_api_url(api_url: str, server_url: str) -> str:
    """Адрес API: заданный явно или выведенный из адреса сервера.

    Forgejo Actions не всегда передаёт ``github.api_url``, зато адрес сервера
    известен всегда: API Forgejo живёт по ``<сервер>/api/v1``.
    """
    explicit = api_url.strip().rstrip("/")
    if explicit:
        return explicit
    server = server_url.strip().rstrip("/")
    if not server:
        raise ReleaseError("нужен адрес API: GITHUB_API_URL или GITHUB_SERVER_URL")
    host = urllib.parse.urlsplit(server).hostname or ""
    if host == "github.com" or host.endswith(".github.com"):
        return "https://api.github.com"
    return f"{server}/api/v1"


def is_tls_error(error: BaseException) -> bool:
    """Признак отказа из-за сертификата TLS, а не логики запроса."""
    text = str(error).upper()
    return "CERTIFICATE_VERIFY_FAILED" in text or "SSL" in text


def _multipart(asset: pathlib.Path) -> tuple[str, bytes]:
    """Тело form-data с одним полем ``attachment`` — так ждёт Forgejo."""
    boundary = f"----asustor-adm-{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="attachment"; '
        f'filename="{asset.name}"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return boundary, head + asset.read_bytes() + tail


class ReleaseClient:
    """Идемпотентный клиент релизов поверх API GitHub/Forgejo."""

    def __init__(
        self,
        settings: Settings,
        transport: Transport | None = None,
        insecure_transport: Transport | None = None,
        log: Any = print,
    ) -> None:
        self.settings = settings
        self.transport: Transport = transport or UrllibTransport()
        self.insecure_transport: Transport = insecure_transport or UrllibTransport(
            insecure=True
        )
        self.log = log

    @property
    def _base(self) -> str:
        return self.settings.api_url.rstrip("/")

    @property
    def _releases(self) -> str:
        return f"/repos/{self.settings.repository}/releases"

    def _headers(self, **extra: str) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.settings.token:
            # Forgejo ждёт схему token для своих токенов, GitHub — Bearer.
            scheme = "Bearer" if self.settings.engine == ENGINE_GITHUB else "token"
            headers["Authorization"] = f"{scheme} {self.settings.token}"
        headers.update(extra)
        return headers

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes | None = None,
    ) -> Response:
        try:
            return self.transport.send(method, url, headers=headers, data=data)
        except ReleaseError as error:
            # Внутренний Forgejo часто отдаёт самоподписанный сертификат,
            # которого нет в доверенных на раннере: повторяем без проверки.
            if self.settings.engine == ENGINE_GITHUB or not is_tls_error(error):
                raise
            self.log("сертификат API не проверен: повтор запроса без проверки TLS")
            return self.insecure_transport.send(method, url, headers=headers, data=data)

    def _ensure(
        self, response: Response, action: str, allowed: tuple[int, ...] = (200, 201)
    ) -> None:
        if response.status in allowed:
            return
        detail = response.body[:500].decode("utf-8", errors="replace")
        raise ReleaseError(f"{action}: HTTP {response.status}: {detail}")

    def find(self, tag: str) -> dict[str, Any] | None:
        """Релиз по тегу или ``None``, если его нет."""
        url = f"{self._base}{self._releases}/tags/{urllib.parse.quote(tag, safe='')}"
        response = self._send("GET", url, headers=self._headers())
        if response.status == 404:
            return None
        self._ensure(response, "получение релиза")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ReleaseError("ответ о релизе не является объектом")
        return payload

    def create(self, tag: str, body: str, *, draft: bool) -> dict[str, Any]:
        """Создать релиз; черновик не виден пользователям и HACS."""
        payload = {
            "tag_name": tag,
            "name": tag,
            "body": body,
            "draft": draft,
            "prerelease": False,
        }
        response = self._send(
            "POST",
            f"{self._base}{self._releases}",
            headers=self._headers(**{"Content-Type": "application/json"}),
            data=json.dumps(payload).encode("utf-8"),
        )
        self._ensure(response, "создание релиза")
        return self._release(response)

    def update(self, release_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Изменить релиз: тело или признак черновика."""
        response = self._send(
            "PATCH",
            f"{self._base}{self._releases}/{release_id}",
            headers=self._headers(**{"Content-Type": "application/json"}),
            data=json.dumps(dict(payload)).encode("utf-8"),
        )
        self._ensure(response, "обновление релиза")
        return self._release(response)

    def _release(self, response: Response) -> dict[str, Any]:
        payload = response.json()
        if not isinstance(payload, dict) or "id" not in payload:
            raise ReleaseError("ответ не содержит идентификатора релиза")
        return payload

    def _upload_url(self) -> str:
        """Адрес загрузки вложений: у GitHub это отдельный хост."""
        host = urllib.parse.urlsplit(self._base).hostname or ""
        if host == "api.github.com":
            return "https://uploads.github.com"
        return self._base

    def upload(self, release_id: int, asset: pathlib.Path) -> None:
        """Загрузить архив плагина как вложение релиза."""
        name = urllib.parse.quote(asset.name, safe="")
        path = f"{self._releases}/{release_id}/assets?name={name}"
        if self.settings.engine == ENGINE_GITHUB:
            response = self._send(
                "POST",
                f"{self._upload_url()}{path}",
                headers=self._headers(**{"Content-Type": "application/zip"}),
                data=asset.read_bytes(),
            )
        else:
            boundary, payload = _multipart(asset)
            response = self._send(
                "POST",
                f"{self._base}{path}",
                headers=self._headers(
                    **{"Content-Type": f"multipart/form-data; boundary={boundary}"}
                ),
                data=payload,
            )
        self._ensure(response, f"загрузка ассета {asset.name}")

    def delete_asset(self, release_id: int, asset_id: int) -> None:
        """Удалить вложение, чтобы заменить его актуальным архивом."""
        if self.settings.engine == ENGINE_GITHUB:
            path = f"/repos/{self.settings.repository}/releases/assets/{asset_id}"
        else:
            path = f"{self._releases}/{release_id}/assets/{asset_id}"
        response = self._send("DELETE", f"{self._base}{path}", headers=self._headers())
        self._ensure(response, "удаление ассета", allowed=(200, 204))

    @staticmethod
    def _find_asset(release: Mapping[str, Any], name: str) -> dict[str, Any] | None:
        """Вложение по имени: Forgejo отдаёт ``assets``, старые — ``attachments``."""
        items = release.get("assets") or release.get("attachments") or []
        for item in items:
            if isinstance(item, dict) and item.get("name") == name:
                return item
        return None

    def publish(self, *, tag: str, body: str, asset: pathlib.Path) -> str:
        """Создать или дозаполнить релиз и опубликовать его с архивом."""
        asset = pathlib.Path(asset)
        if not asset.is_file():
            raise ReleaseError(f"нет файла архива {asset}")
        release = self.find(tag)
        if release is None:
            self.log(f"создаю черновик релиза {tag}")
            release = self.create(tag, body, draft=True)
        else:
            self.log(f"релиз {tag} уже существует")
            if not release.get("body") and body:
                self.log("заполняю пустое тело релиза")
                release = self.update(int(release["id"]), {"body": body})
        self._sync_asset(release, asset)
        if release.get("draft", False):
            self.log(f"публикую релиз {tag}")
            release = self.update(int(release["id"]), {"draft": False})
        return str(release.get("html_url") or tag)

    def _sync_asset(self, release: Mapping[str, Any], asset: pathlib.Path) -> None:
        """Догнать вложение до локального файла: загрузить или заменить."""
        release_id = int(release["id"])
        size = asset.stat().st_size
        existing = self._find_asset(release, asset.name)
        if existing is not None and existing.get("size") == size:
            self.log(f"ассет {asset.name} уже загружен ({size} байт)")
            return
        if existing is not None:
            self.log(f"заменяю устаревший ассет {asset.name}")
            self.delete_asset(release_id, int(existing["id"]))
        self.log(f"загружаю {asset.name} ({size} байт)")
        self.upload(release_id, asset)


def _env(*names: str, default: str = "") -> str:
    """Первое непустое значение из переменных окружения."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Релиз с архивом плагина на GitHub или Forgejo.",
    )
    parser.add_argument("--tag", required=True, help="тег релиза, например v0.2.0")
    parser.add_argument("--asset", type=pathlib.Path, help="архив плагина")
    parser.add_argument("--notes-file", type=pathlib.Path, help="файл с текстом релиза")
    parser.add_argument(
        "--api-url",
        default=_env("GITHUB_API_URL", "API_URL"),
        help="адрес API (по умолчанию GITHUB_API_URL)",
    )
    parser.add_argument(
        "--server-url",
        default=_env("GITHUB_SERVER_URL", "SERVER_URL"),
        help="адрес сервера для вывода API (по умолчанию GITHUB_SERVER_URL)",
    )
    parser.add_argument(
        "--repo",
        default=_env("GITHUB_REPOSITORY", "REPOSITORY"),
        help="репозиторий owner/name (по умолчанию GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--token",
        default=_env("GITHUB_TOKEN", "GH_TOKEN", "RELEASE_TOKEN"),
        help="токен API (по умолчанию GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--engine",
        choices=ENGINES,
        default=_env("RELEASE_ENGINE") or None,
        help="движок API (по умолчанию определяется по адресу API)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="напечатать exists или missing и выйти",
    )
    parser.add_argument("--dry-run", action="store_true", help="ничего не публиковать")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, transport: Transport | None = None) -> int:
    """Точка входа CLI: адрес релиза в stdout, сообщения в stderr."""
    args = _parse_args(argv)
    try:
        if not args.repo:
            raise ReleaseError("нужен репозиторий owner/name")
        api_url = resolve_api_url(args.api_url, args.server_url)
        engine = args.engine or detect_engine(api_url)
        # Адрес и движок не секретны: без них отказ API трудно объяснить.
        print(
            f"API {api_url}, репозиторий {args.repo}, движок {engine}", file=sys.stderr
        )
        settings = Settings(
            api_url=api_url,
            repository=args.repo,
            token=args.token,
            engine=engine,
        )
        client = ReleaseClient(settings, transport=transport)
        if args.check:
            release = client.find(args.tag)
            published = release is not None and not release.get("draft", False)
            print("exists" if published else "missing")
            return 0
        if args.asset is None or args.notes_file is None:
            raise ReleaseError("нужны --asset и --notes-file")
        body = args.notes_file.read_text(encoding="utf-8").strip()
        if not body:
            raise ReleaseError("текст релиза пуст")
        if not args.asset.is_file():
            raise ReleaseError(f"нет файла архива {args.asset}")
        if args.dry_run:
            size = args.asset.stat().st_size
            print(
                f"черновик {args.tag}, ассет {args.asset.name} ({size} байт), "
                f"затем публикация; API {api_url}, движок {engine}"
            )
            return 0
        url = client.publish(tag=args.tag, body=body, asset=args.asset)
        print(url)
        return 0
    except (ReleaseError, OSError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
