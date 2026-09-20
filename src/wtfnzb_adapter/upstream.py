"""Single-instance, serialized, bounded upstream access; no automatic HTTP retries."""

import asyncio
import fcntl
import time
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, BinaryIO

import anyio
import httpx
import msgspec

from wtfnzb_adapter.config import Settings, read_credentials
from wtfnzb_adapter.models import AdapterError, Credentials
from wtfnzb_adapter.session import environment
from wtfnzb_adapter.session_budget import capture_with_budget
from wtfnzb_adapter.state import Budget, private_write

if TYPE_CHECKING:
    from pathlib import Path


class Upstream:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings: Settings = settings
        self.credentials: Credentials = read_credentials(settings.auth_file)
        settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock_file: BinaryIO = (settings.state_dir / "instance.lock").open("ab")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise ValueError(
                "Another adapter instance owns this state directory; use one worker"
            ) from None
        self.state_path: Path = settings.state_dir / "budget.json"
        self.budget: Budget = (
            msgspec.json.decode(self.state_path.read_bytes(), type=Budget)
            if self.state_path.exists()
            else Budget()
        )
        self.client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        )
        self.lock: asyncio.Lock = asyncio.Lock()

    async def close(self) -> None:
        await self.client.aclose()
        self.lock_file.close()

    async def save(self) -> None:
        await anyio.to_thread.run_sync(
            private_write, self.state_path, msgspec.json.encode(self.budget)
        )

    async def prepare(self) -> None:
        async with self.lock:
            await self._prepare_unlocked()

    async def _prepare_unlocked(self) -> None:
        current = await anyio.to_thread.run_sync(read_credentials, self.settings.auth_file)
        if current != self.credentials:
            self.credentials = current
            self.budget.auth_blocked = False
        if self.budget.auth_blocked and self.settings.auto_session:
            env = await anyio.to_thread.run_sync(environment)
            env.update(
                {
                    "WTFNZB_BASE_URL": self.credentials.base_url,
                    "WTFNZB_AUTH_FILE": str(self.settings.auth_file),
                    "ADAPTER_STATE_DIR": str(self.settings.state_dir),
                }
            )
            refresh = asyncio.create_task(capture_with_budget(env, running_budget=self.budget))
            try:
                refreshed = await asyncio.shield(refresh)
            except asyncio.CancelledError:
                _ = await refresh
                raise
            if refreshed:
                self.credentials = await anyio.to_thread.run_sync(
                    read_credentials, self.settings.auth_file
                )
                self.budget.auth_blocked = False
                await self.save()
        if self.budget.auth_blocked:
            raise AdapterError(
                "Upstream authentication blocked; refresh the protected session file", 100, 503
            )

    async def request(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
        session: bool = True,
        max_bytes: int = 2_000_000,
    ) -> bytes:
        async with self.lock:
            await self._prepare_unlocked()
            now = time.time()
            self.budget.requests = [t for t in self.budget.requests if t > now - 86400]
            if (
                self.budget.cooldown_until > now
                or len(self.budget.requests) >= self.settings.daily_budget
                or sum(t > now - 3600 for t in self.budget.requests) >= self.settings.hourly_budget
            ):
                raise AdapterError(
                    "Upstream request budget or cooldown reached; retry later", 500, 429
                )
            if self.budget.requests:
                await asyncio.sleep(
                    max(0, self.settings.spacing - (now - self.budget.requests[-1]))
                )
            self.budget.requests.append(time.time())
            await self.save()
            headers = {"Cookie": f"PHPSESSID={self.credentials.session}"} if session else {}
            files = {key: (None, value) for key, value in form.items()} if form else None
            if form:
                headers["X-Requested-With"] = "XMLHttpRequest"
            self.client.cookies.clear()
            try:
                async with (
                    asyncio.timeout(35),
                    self.client.stream(
                        "POST" if form else "GET",
                        self.credentials.base_url.rstrip("/") + path,
                        params=params,
                        files=files,
                        headers=headers,
                    ) as response,
                ):
                    if response.status_code == 429:
                        retry = dict(response.headers.multi_items()).get("retry-after", "3600")
                        delay = retry_delay(retry)
                        self.budget.cooldown_until = time.time() + max(60, delay)
                        await self.save()
                        raise AdapterError("Upstream rate limit; cooling down", 500, 429)
                    if response.status_code in {301, 302, 303, 307, 308, 401, 403}:
                        self.budget.auth_blocked = True
                        await self.save()
                        raise AdapterError(
                            "Upstream session expired or access was denied; refresh session",
                            100,
                            503,
                        )
                    if response.status_code != 200:
                        self.budget.cooldown_until = time.time() + 60
                        await self.save()
                        raise AdapterError(
                            f"Upstream HTTP {response.status_code}; no retry was sent"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise AdapterError("Upstream response exceeds the bounded read limit")
                    raw = bytes(body)
                    if b'type="password"' in raw or b"Error 1106" in raw:
                        self.budget.auth_blocked = True
                        await self.save()
                        raise AdapterError("Upstream returned a login or blocked-IP page", 100, 503)
                    return raw
            except httpx.HTTPError, TimeoutError:
                self.budget.cooldown_until = time.time() + 60
                await self.save()
                raise AdapterError(
                    "Upstream request timed out or failed; partial response discarded"
                ) from None


def retry_delay(value: str) -> float:
    if value.isdigit():
        return float(value)
    try:
        date = parsedate_to_datetime(value)
        return max(60, date.timestamp() - time.time()) if date.tzinfo else 3600
    except ValueError, OverflowError:
        return 3600
