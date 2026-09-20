import time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import msgspec
import pytest
from litestar.testing import AsyncTestClient

from wtfnzb_adapter.app import create_app
from wtfnzb_adapter.config import Settings
from wtfnzb_adapter.models import AdapterError, Credentials, Search
from wtfnzb_adapter.service import Service
from wtfnzb_adapter.state import private_write
from wtfnzb_adapter.upstream import Upstream

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    auth = tmp_path / "auth.json"
    private_write(
        auth,
        msgspec.json.encode(
            Credentials("https://upstream.example", "dummy-api", "123", "dummy-session")
        ),
    )
    return Settings(
        "test-adapter-key-with-24-characters",
        "https://adapter.example",
        auth,
        tmp_path / "state",
        ZoneInfo("Europe/Copenhagen"),
        spacing=0,
    )


def make_service(settings: Settings, handler: Callable[[httpx.Request], httpx.Response]) -> Service:
    return Service(Upstream(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler))))


@pytest.mark.anyio
async def test_app_rss_cache_auth_and_unsupported(settings: Settings, evidence: Path) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=(evidence / "rss-all.xml").read_bytes())

    service = make_service(settings, upstream)
    async with AsyncTestClient(create_app(settings, service)) as client:
        response = await client.get("/api", params={"t": "caps", "apikey": settings.adapter_key})
        assert response.status_code == 200 and b"<caps>" in response.content
        response = await client.get("/api", params={"t": "search", "apikey": "bad"})
        assert response.status_code == 401
        response = await client.get(
            "/api", params={"t": "movie", "imdbid": "123", "apikey": settings.adapter_key}
        )
        assert response.status_code == 400 and b'code="202"' in response.content
        for offset in (0, 5):
            response = await client.get(
                "/api",
                params={
                    "t": "search",
                    "cat": "5000",
                    "offset": str(offset),
                    "apikey": settings.adapter_key,
                },
            )
            assert response.status_code == 200
            assert b'length="189' in response.content
        assert len(requests) == 1
        assert "cookie" not in requests[0].headers


@pytest.mark.anyio
async def test_archive_bounds_enrichment_and_no_partial_cache(
    settings: Settings, evidence: Path
) -> None:
    paths: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(200, content=(evidence / "archive-matrix-100.html").read_bytes())
        if request.url.path.startswith("/details/"):
            return httpx.Response(
                200, content=(evidence / "detail-matrix-metadata.html").read_bytes()
            )
        return httpx.Response(200, text="const csrfToken = 'fake-token';")

    service = make_service(settings, upstream)
    try:
        result = await service.search(Search(query="The.Matrix.1999", categories=(2000,)))
        assert len(result.releases) == 5
        assert len(paths) == 7
        _ = await service.search(Search(query="The.Matrix.1999", categories=(2000,)))
        assert len(paths) == 7
    finally:
        await service.upstream.close()


@pytest.mark.anyio
async def test_rate_limit_persists_and_auth_latches(settings: Settings) -> None:
    count = 0

    def denied(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(403)

    service = make_service(settings, denied)
    try:
        for _ in range(2):
            with pytest.raises(AdapterError, match=r"session|authentication"):
                _ = await service.upstream.request("/details/test")
        assert count == 1
    finally:
        await service.upstream.close()
    service = make_service(settings, denied)
    try:
        with pytest.raises(AdapterError, match="authentication"):
            _ = await service.upstream.request("/details/test")
        assert count == 1
    finally:
        await service.upstream.close()


@pytest.mark.anyio
async def test_cooldown_byte_limit_and_budget(settings: Settings) -> None:
    service = make_service(settings, lambda _: httpx.Response(429, headers={"Retry-After": "7200"}))
    try:
        with pytest.raises(AdapterError, match="cooling"):
            _ = await service.upstream.request("/rss")
        assert service.upstream.budget.cooldown_until > time.time() + 7000
        with pytest.raises(AdapterError, match="budget"):
            _ = await service.upstream.request("/rss")
        service.upstream.budget.cooldown_until = 0
        service.upstream.budget.requests = [time.time()] * 60
        with pytest.raises(AdapterError, match="budget"):
            _ = await service.upstream.request("/rss")
    finally:
        await service.upstream.close()


@pytest.mark.anyio
async def test_oversized_and_transport_failure(settings: Settings) -> None:
    service = make_service(settings, lambda _: httpx.Response(200, content=b"too long"))
    try:
        with pytest.raises(AdapterError, match="bounded"):
            _ = await service.upstream.request("/rss", max_bytes=3)
    finally:
        await service.upstream.close()


@pytest.mark.anyio
async def test_prowlarr_basic_tv_fallback_uses_catalogue(
    settings: Settings, evidence: Path
) -> None:
    paths: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/series":
            return httpx.Response(200, text='<a href="/series/123">Outlander Blood of My Blood</a>')
        return httpx.Response(
            200,
            content=b"<html>" + (evidence / "series-release-rows.html").read_bytes() + b"</html>",
        )

    service = make_service(settings, upstream)
    try:
        result = await service.search(
            Search(query="Outlander Blood of My Blood", categories=(5000,))
        )
        assert len(result.releases) == 2
        assert paths == ["/series", "/series/123"]
        same = await service.search(
            Search(mode="tvsearch", query="Outlander Blood of My Blood", categories=(5000,))
        )
        assert same == result and len(paths) == 2
    finally:
        await service.upstream.close()


@pytest.mark.anyio
async def test_partial_failure_cache_prevents_prowlarr_retry_amplification(
    settings: Settings, evidence: Path
) -> None:
    count = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if request.method == "POST":
            return httpx.Response(
                200, content=(evidence / "archive-casablanca-4.html").read_bytes()
            )
        return httpx.Response(200, text="const csrfToken = 'fake-token';")

    service = make_service(settings, upstream)
    try:
        for mode in ("search", "movie", "search"):
            with pytest.raises(AdapterError, match="incomplete"):
                _ = await service.search(Search(mode=mode, query="Casablanca.1942"))
        assert count == 2
    finally:
        await service.upstream.close()


@pytest.mark.anyio
async def test_session_refresh_precedes_csrf_selection(
    settings: Settings, evidence: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wtfnzb_adapter.state import Budget

    settings = msgspec.structs.replace(settings, auto_session=True)
    calls: list[str] = []

    async def capture(_env: dict[str, str], *, running_budget: Budget | None = None) -> bool:
        assert running_budget is not None
        private_write(
            settings.auth_file,
            msgspec.json.encode(
                Credentials("https://upstream.example", "new-api", "123", "renewed-session")
            ),
        )
        calls.append("refresh")
        return True

    monkeypatch.setattr("wtfnzb_adapter.upstream.capture_with_budget", capture)
    monkeypatch.setattr("wtfnzb_adapter.upstream.environment", dict)

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.headers["cookie"] == "PHPSESSID=renewed-session"
        if request.method == "POST":
            assert b"fresh-token" in request.content
            return httpx.Response(200, content=(evidence / "archive-matrix-100.html").read_bytes())
        if request.url.path.startswith("/details/"):
            return httpx.Response(
                200, content=(evidence / "detail-matrix-metadata.html").read_bytes()
            )
        calls.append("bootstrap")
        return httpx.Response(200, text="const csrfToken = 'fresh-token';")

    service = make_service(settings, upstream)
    service.csrf = "stale-token"
    service.csrf_session = "dummy-session"
    service.upstream.budget.auth_blocked = True
    try:
        result = await service.search(Search(query="The.Matrix.1999"))
        assert result.releases and calls == ["refresh", "bootstrap"]
    finally:
        await service.upstream.close()
