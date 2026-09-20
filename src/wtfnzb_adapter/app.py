import hmac
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from litestar import Controller, Litestar, Response, get
from litestar.di import NamedDependency, Provide
from litestar.logging import LoggingConfig
from litestar.params import FromQuery
from litestar_granian import GranianPlugin

from wtfnzb_adapter import newznab
from wtfnzb_adapter.config import Settings, settings_from_env
from wtfnzb_adapter.models import AdapterError, Search
from wtfnzb_adapter.service import Service
from wtfnzb_adapter.upstream import Upstream

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class IndexerController(Controller):
    path: str = "/"

    @get("health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok", "scope": "experimental"}

    @get("api")
    async def api(
        self,
        service: NamedDependency[Service],
        settings: NamedDependency[Settings],
        t: FromQuery[str] = "caps",
        apikey: FromQuery[str] = "",
        q: FromQuery[str] = "",
        cat: FromQuery[str] = "",
        limit: FromQuery[int] = 5,
        offset: FromQuery[int] = 0,
        season: FromQuery[int | None] = None,
        ep: FromQuery[int | None] = None,
        id: FromQuery[str] = "",
        imdbid: FromQuery[str] = "",
        tvdbid: FromQuery[str] = "",
        rid: FromQuery[str] = "",
        tmdbid: FromQuery[str] = "",
        tvmazeid: FromQuery[str] = "",
    ) -> Response[bytes]:
        try:
            if not hmac.compare_digest(apikey, settings.adapter_key):
                raise AdapterError("Invalid adapter API key", 100, 401)
            if t == "caps":
                body = newznab.caps()
            elif t == "get":
                body = await service.download(id)
                return Response(
                    body,
                    media_type="application/x-nzb",
                    headers={"Content-Disposition": f'attachment; filename="{id}.nzb"'},
                )
            elif t in {"search", "tvsearch", "movie"}:
                if any((imdbid, tvdbid, rid, tmdbid, tvmazeid)):
                    raise AdapterError("Identifier searches are not supported; supply q", 202, 400)
                if (
                    not 1 <= limit <= 100
                    or offset < 0
                    or len(q) > 200
                    or (q and len(q.strip()) < 3)
                ):
                    raise AdapterError("Invalid search length or pagination", 200, 400)
                if season is not None and (season < 0 or season > 999):
                    raise AdapterError("Invalid season", 200, 400)
                if ep is not None and (season is None or ep < 0 or ep > 999):
                    raise AdapterError("Episode requires a numeric season", 200, 400)
                if t != "tvsearch" and (season is not None or ep is not None):
                    raise AdapterError("Season and episode require tvsearch", 200, 400)
                try:
                    categories = tuple(sorted({int(c) for c in cat.split(",") if c}))
                except ValueError:
                    raise AdapterError("Invalid categories", 200, 400) from None
                if not set(categories) <= newznab.KNOWN_CATEGORIES:
                    raise AdapterError("Unsupported category", 200, 400)
                snapshot = await service.search(Search(t, q.strip(), categories, season, ep))
                body = newznab.feed(
                    snapshot, settings.public_url, settings.adapter_key, offset, limit
                )
            else:
                raise AdapterError("Unsupported function", 202, 400)
            return Response(body, media_type="application/xml")
        except AdapterError as exc:
            return Response(
                newznab.error(exc), status_code=exc.status, media_type="application/xml"
            )


def create_app(settings: Settings | None = None, service: Service | None = None) -> Litestar:
    config = settings or settings_from_env()
    indexer: Service | None = service

    def provide_service() -> Service:
        if indexer is None:
            raise RuntimeError("Application has not started")
        return indexer

    def provide_settings() -> Settings:
        return config

    @asynccontextmanager
    async def lifespan(_app: Litestar) -> AsyncGenerator[None]:
        nonlocal indexer
        indexer = service or Service(Upstream(config))
        try:
            yield
        finally:
            await indexer.upstream.close()

    return Litestar(
        route_handlers=[IndexerController],
        dependencies={
            "service": Provide(provide_service, sync_to_thread=False),
            "settings": Provide(provide_settings, sync_to_thread=False),
        },
        lifespan=[lifespan],
        plugins=[GranianPlugin()],
        openapi_config=None,
        debug=False,
        logging_config=LoggingConfig(
            loggers={"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}}
        ),
    )
