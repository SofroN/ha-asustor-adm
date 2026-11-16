"""Проверки публикации релиза: атомарность, идемпотентность, два движка.

Транспорт подменяется сценарием ответов, поэтому тест видит
последовательность HTTP-вызовов и тела запросов: именно от них зависит,
появится ли у пользователя релиз с архивом или пустой черновик.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from dataclasses import dataclass

import pytest

ROOT = pathlib.Path(__file__).parents[2]


def _load_publish_release():
    """Загрузить скрипт публикации как модуль."""
    path = ROOT / "scripts" / "publish_release.py"
    spec = importlib.util.spec_from_file_location("publish_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass(slots=True) ищет модуль в sys.modules: регистрируем заранее.
    sys.modules["publish_release"] = module
    spec.loader.exec_module(module)
    return module


publish_release = _load_publish_release()


@dataclass(frozen=True, slots=True)
class Call:
    """Один HTTP-вызов, сделанный клиентом."""

    method: str
    url: str
    headers: dict[str, str]
    data: bytes | None


class FakeTransport:
    """Транспорт со сценарием ответов и журналом вызовов."""

    def __init__(self, *responses: tuple[int, dict[str, object] | None]) -> None:
        self._responses = list(responses)
        self.calls: list[Call] = []

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: bytes | None,
    ) -> publish_release.Response:
        self.calls.append(Call(method, url, dict(headers), data))
        assert self._responses, f"неожиданный запрос {method} {url}"
        status, payload = self._responses.pop(0)
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return publish_release.Response(status=status, body=body)


def _settings(engine: str = publish_release.ENGINE_GITEA) -> object:
    return publish_release.Settings(
        api_url="https://forgejo.example/api/v1",
        repository="SofroN/ha-asustor-adm",
        token="secret",
        engine=engine,
    )


def _client(transport: FakeTransport, engine: str = publish_release.ENGINE_GITEA):
    return publish_release.ReleaseClient(
        _settings(engine), transport=transport, log=lambda *args: None
    )


@pytest.fixture()
def asset(tmp_path: pathlib.Path) -> pathlib.Path:
    """Архив плагина, который прикладывается к релизу."""
    path = tmp_path / "asustor_adm-0.2.0.zip"
    path.write_bytes(b"PK\x03\x04 archive")
    return path


def test_publish_creates_draft_uploads_asset_and_publishes(asset: pathlib.Path) -> None:
    """Новый релиз: черновик, архив, публикация — именно в этом порядке."""
    transport = FakeTransport(
        (404, None),
        (201, {"id": 11, "draft": True, "html_url": "https://host/releases/11"}),
        (201, {"id": 21, "name": asset.name, "size": asset.stat().st_size}),
        (200, {"id": 11, "draft": False, "html_url": "https://host/releases/v0.2.0"}),
    )
    url = _client(transport).publish(tag="v0.2.0", body="список изменений", asset=asset)
    assert url == "https://host/releases/v0.2.0"
    assert [call.method for call in transport.calls] == ["GET", "POST", "POST", "PATCH"]
    created = json.loads(transport.calls[1].data or b"{}")
    assert created["tag_name"] == "v0.2.0"
    assert created["draft"] is True
    assert created["body"] == "список изменений"
    assert "assets?name=asustor_adm-0.2.0.zip" in transport.calls[2].url
    assert json.loads(transport.calls[3].data or b"{}") == {"draft": False}


def test_published_release_with_matching_asset_is_untouched(
    asset: pathlib.Path,
) -> None:
    """Повторный запуск не меняет опубликованный релиз с тем же архивом."""
    transport = FakeTransport(
        (
            200,
            {
                "id": 11,
                "draft": False,
                "body": "текст",
                "html_url": "https://host/releases/v0.2.0",
                "assets": [
                    {"id": 21, "name": asset.name, "size": asset.stat().st_size}
                ],
            },
        )
    )
    url = _client(transport).publish(tag="v0.2.0", body="текст", asset=asset)
    assert url == "https://host/releases/v0.2.0"
    assert [call.method for call in transport.calls] == ["GET"]


def test_stale_asset_is_replaced(asset: pathlib.Path) -> None:
    """Ассет другого размера пересобирается: архив должен соответствовать версии."""
    transport = FakeTransport(
        (
            200,
            {
                "id": 11,
                "draft": False,
                "body": "текст",
                "html_url": "https://host/releases/v0.2.0",
                "assets": [{"id": 21, "name": asset.name, "size": 1}],
            },
        ),
        (204, None),
        (201, {"id": 22, "name": asset.name, "size": asset.stat().st_size}),
    )
    _client(transport).publish(tag="v0.2.0", body="текст", asset=asset)
    assert [call.method for call in transport.calls] == ["GET", "DELETE", "POST"]
    assert transport.calls[1].url.endswith("/releases/11/assets/21")


def test_failed_upload_keeps_release_unpublished(asset: pathlib.Path) -> None:
    """Сбой загрузки не публикует релиз: черновик остаётся, повтора нет."""
    transport = FakeTransport(
        (404, None),
        (201, {"id": 11, "draft": True}),
        (500, {"message": "boom"}),
    )
    with pytest.raises(publish_release.ReleaseError):
        _client(transport).publish(tag="v0.2.0", body="текст", asset=asset)
    assert [call.method for call in transport.calls] == ["GET", "POST", "POST"]
    assert not [call for call in transport.calls if call.method == "PATCH"]


def test_empty_body_of_draft_is_filled(asset: pathlib.Path) -> None:
    """Черновик без текста получает список изменений перед публикацией."""
    transport = FakeTransport(
        (200, {"id": 11, "draft": True, "body": "", "assets": []}),
        (200, {"id": 11, "draft": True, "body": "текст", "assets": []}),
        (201, {"id": 21, "name": asset.name, "size": asset.stat().st_size}),
        (200, {"id": 11, "draft": False, "html_url": "https://host/releases/v0.2.0"}),
    )
    _client(transport).publish(tag="v0.2.0", body="текст", asset=asset)
    assert [call.method for call in transport.calls] == [
        "GET",
        "PATCH",
        "POST",
        "PATCH",
    ]
    assert json.loads(transport.calls[1].data or b"{}") == {"body": "текст"}
    assert json.loads(transport.calls[3].data or b"{}") == {"draft": False}


def test_github_upload_uses_uploads_host(asset: pathlib.Path) -> None:
    """GitHub принимает архив двоичным телом на отдельном хосте загрузки."""
    transport = FakeTransport(
        (404, None),
        (201, {"id": 11, "draft": True}),
        (201, {"id": 21, "name": asset.name, "size": asset.stat().st_size}),
        (200, {"id": 11, "draft": False, "html_url": "https://github.com/o/r"}),
    )
    client = publish_release.ReleaseClient(
        publish_release.Settings(
            api_url="https://api.github.com",
            repository="SofroN/ha-asustor-adm",
            token="secret",
            engine=publish_release.ENGINE_GITHUB,
        ),
        transport=transport,
        log=lambda *args: None,
    )
    client.publish(tag="v0.2.0", body="текст", asset=asset)
    upload = transport.calls[2]
    assert upload.url.startswith(
        "https://uploads.github.com/repos/SofroN/ha-asustor-adm/releases/11/assets"
    )
    assert upload.headers["Content-Type"] == "application/zip"
    assert upload.data == asset.read_bytes()


def test_gitea_upload_uses_multipart(asset: pathlib.Path) -> None:
    """Forgejo ожидает multipart с полем attachment и именем в query."""
    transport = FakeTransport(
        (404, None),
        (201, {"id": 11, "draft": True}),
        (201, {"id": 21, "name": asset.name, "size": asset.stat().st_size}),
        (200, {"id": 11, "draft": False, "html_url": "https://host/releases/v0.2.0"}),
    )
    _client(transport).publish(tag="v0.2.0", body="текст", asset=asset)
    upload = transport.calls[2]
    assert upload.url.startswith("https://forgejo.example/api/v1/repos/")
    content_type = upload.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="attachment"; filename="asustor_adm-0.2.0.zip"' in upload.data
    assert asset.read_bytes() in upload.data


def test_find_returns_none_for_missing_release() -> None:
    """Отсутствующий релиз — не ошибка, а повод его создать."""
    transport = FakeTransport((404, None))
    assert _client(transport).find("v0.2.0") is None


def test_find_raises_on_api_failure() -> None:
    """Отказ API при чтении релиза — ошибка, а не «релиза нет»."""
    transport = FakeTransport((500, {"message": "boom"}))
    with pytest.raises(publish_release.ReleaseError):
        _client(transport).find("v0.2.0")


@pytest.mark.parametrize(
    ("api_url", "expected"),
    [
        ("https://api.github.com", publish_release.ENGINE_GITHUB),
        ("https://forgejo.example/api/v1", publish_release.ENGINE_GITEA),
        ("https://git.example/gitea/api/v1", publish_release.ENGINE_GITEA),
    ],
)
def test_detect_engine(api_url: str, expected: str) -> None:
    """Движок определяется по адресу API, если не задан явно."""
    assert publish_release.detect_engine(api_url) == expected


def test_check_reports_missing_for_draft(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Черновик считается отсутствующим: его нужно довести до публикации."""
    transport = FakeTransport((200, {"id": 11, "draft": True, "assets": []}))
    code = publish_release.main(
        [
            "--tag",
            "v0.2.0",
            "--check",
            "--repo",
            "o/r",
            "--token",
            "t",
            "--api-url",
            "https://forgejo.example/api/v1",
        ],
        transport=transport,
    )
    assert code == 0
    assert capsys.readouterr().out.strip() == "missing"


def test_dry_run_makes_no_requests(
    asset: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Пробный прогон показывает план и не обращается к API."""
    notes = tmp_path / "notes.md"
    notes.write_text("текст", encoding="utf-8")
    transport = FakeTransport()
    code = publish_release.main(
        [
            "--tag",
            "v0.2.0",
            "--asset",
            str(asset),
            "--notes-file",
            str(notes),
            "--dry-run",
            "--repo",
            "o/r",
            "--token",
            "t",
            "--api-url",
            "https://forgejo.example/api/v1",
        ],
        transport=transport,
    )
    assert code == 0
    assert not transport.calls
    assert "asustor_adm-0.2.0.zip" in capsys.readouterr().out


def test_cli_requires_asset_and_notes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Без архива и текста релиза публикация не начинается."""
    code = publish_release.main(
        ["--tag", "v0.2.0", "--repo", "o/r", "--api-url", "https://host/api/v1"],
        transport=FakeTransport(),
    )
    assert code == 2
    assert "ошибка" in capsys.readouterr().err
