import asyncio
import re
import time
from collections import OrderedDict
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import anyio
import msgspec
from bs4 import BeautifulSoup

from wtfnzb_adapter import parsing
from wtfnzb_adapter.models import AdapterError, Release, Search, Snapshot

if TYPE_CHECKING:
    from wtfnzb_adapter.upstream import Upstream


def category_matches(category: int, requested: tuple[int, ...]) -> bool:
    if not requested:
        return True
    parent = 8000 if category >= 100000 else category // 1000 * 1000
    return category in requested or parent in requested


class Service:
    def __init__(self, upstream: Upstream) -> None:
        self.upstream: Upstream = upstream
        self.cache: OrderedDict[Search, tuple[float, Snapshot]] = OrderedDict()
        self.metadata: OrderedDict[str, tuple[float, Release]] = OrderedDict()
        self.failures: OrderedDict[Search, tuple[float, str, int, int]] = OrderedDict()
        self.lock: asyncio.Lock = asyncio.Lock()
        self.csrf: str = ""
        self.csrf_session: str = ""

    async def search(self, search: Search) -> Snapshot:
        # Prowlarr falls back to t=search for TV requests without IDs/season/ep.
        # Use explicit TV-only category intent, never a guessed title category.
        tv_categories = bool(search.categories) and all(5000 <= c < 6000 for c in search.categories)
        mode = (
            "tvsearch"
            if search.query and (search.mode == "tvsearch" or tv_categories)
            else "search"
        )
        search = msgspec.structs.replace(search, mode=mode)
        try:
            async with asyncio.timeout(85), self.lock:
                failed = self.failures.get(search)
                if failed and failed[0] > time.monotonic():
                    raise AdapterError(failed[1], failed[2], failed[3])
                cached = self.cache.get(search)
                if cached and cached[0] > time.monotonic():
                    self.cache.move_to_end(search)
                    return cached[1]
                try:
                    snapshot = await self.collect(search)
                except AdapterError as exc:
                    self.failures[search] = (time.monotonic() + 120, str(exc), exc.code, exc.status)
                    while len(self.failures) > 64:
                        _ = self.failures.popitem(last=False)
                    raise
                self.cache[search] = (
                    time.monotonic() + (300 if not search.query else 1800),
                    snapshot,
                )
                while len(self.cache) > 64:
                    _ = self.cache.popitem(last=False)
                return snapshot
        except TimeoutError:
            raise AdapterError(
                "Adapter search deadline reached; partial results discarded", 900, 504
            ) from None

    async def collect(self, search: Search) -> Snapshot:
        await self.upstream.prepare()
        if not search.query:
            upstream_categories = [
                next((k for k, v in parsing.CATEGORY_REMAP.items() if v == cat), cat)
                for cat in search.categories
            ]
            credentials = self.upstream.credentials
            raw = await self.upstream.request(
                "/rss",
                params={
                    "t": ",".join(map(str, upstream_categories)) or "0",
                    "dl": "1",
                    "i": credentials.user_id,
                    "r": credentials.api_key,
                },
                session=False,
            )
            releases = await anyio.to_thread.run_sync(parsing.rss, raw)
            scope = "Current upstream RSS window (at most 50 items)"
        elif search.mode == "tvsearch":
            releases = await self.tv(search.query)
            scope = "Fetched series catalogue; rounded zero-size records omitted; coverage varies by series"
        else:
            releases = await self.archive(search.query)
            scope = f"First {self.upstream.settings.archive_window} matching candidates from one completed upstream search (100 candidate cap); sizes approximate; zero-size records omitted"
        selected = tuple(
            r
            for r in releases
            if r.size > 0
            and category_matches(r.category, search.categories)
            and parsing.matches(r.title, search.query)
            and self.episode_matches(r.title, search)
        )
        return Snapshot(selected, scope)

    @staticmethod
    def episode_matches(title: str, search: Search) -> bool:
        if search.season is None:
            return True
        pattern = rf"(?i)(?<![a-z0-9])s{search.season:02d}"
        pattern += rf"e{search.episode:02d}(?!\d)" if search.episode is not None else r"(?!\d)"
        return re.search(pattern, title) is not None

    async def tv(self, query: str) -> tuple[Release, ...]:
        raw = await self.upstream.request("/series", params={"title": query})
        soup = await anyio.to_thread.run_sync(BeautifulSoup, raw, "html.parser")
        matches: set[str] = set()
        for anchor in soup.select('a[href^="/series/"]'):
            path = urlsplit(parsing.attribute(anchor, "href")).path
            if re.fullmatch(r"/series/\d+", path) and parsing.tokens(
                anchor.get_text(" ", strip=True)
            ) == parsing.tokens(query):
                matches.add(path)
        if len(matches) != 1:
            raise AdapterError(
                "TV catalogue title is absent or ambiguous; general archive search requires non-TV-only categories"
            )
        raw = await self.upstream.request(matches.pop(), max_bytes=8_000_000)
        return await anyio.to_thread.run_sync(parsing.series, raw, self.upstream.settings.timezone)

    async def archive(self, query: str) -> tuple[Release, ...]:
        if not self.csrf or self.csrf_session != self.upstream.credentials.session:
            raw = await self.upstream.request("/_search_.php/_search_")
            match = re.search(rb'const csrfToken\s*=\s*[\'"]([^\'"]+)', raw)
            if not match:
                raise AdapterError("Archive search did not supply a CSRF token")
            self.csrf = match[1].decode()
            self.csrf_session = self.upstream.credentials.session
        raw = await self.upstream.request(
            "/_search_.php/_search_",
            form={"do_search": "1", "csrf": self.csrf, "search": query, "results": "100"},
        )
        candidates = await anyio.to_thread.run_sync(
            parsing.archive, raw, self.upstream.settings.timezone
        )
        candidates = tuple(c for c in candidates if parsing.matches(c.title, query))[
            : self.upstream.settings.archive_window
        ]
        releases: list[Release] = []
        for candidate in candidates:
            cached = self.metadata.get(candidate.guid)
            release = cached[1] if cached and cached[0] > time.monotonic() else None
            if release is None:
                raw = await self.upstream.request(f"/details/{candidate.guid}")
                release = await anyio.to_thread.run_sync(
                    parsing.detail, raw, candidate, self.upstream.settings.timezone
                )
                self.metadata[candidate.guid] = (time.monotonic() + 86400, release)
                while len(self.metadata) > 1000:
                    _ = self.metadata.popitem(last=False)
            releases.append(release)
        return parsing.deduplicate(releases)

    async def download(self, guid: str) -> bytes:
        if not parsing.GUID.fullmatch(guid):
            raise AdapterError("Invalid release ID", 200, 400)
        # The session-backed path is verified for historical TV and movie NZBs.
        raw = await self.upstream.request(f"/getnzb/{guid}", max_bytes=16_000_000)
        return await anyio.to_thread.run_sync(parsing.nzb, raw)
