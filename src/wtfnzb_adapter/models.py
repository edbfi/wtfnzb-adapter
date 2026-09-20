from datetime import datetime
from typing import override

import msgspec


class AdapterError(Exception):
    def __init__(self, message: str, code: int = 900, status: int = 502) -> None:
        super().__init__(message)
        self.code: int = code
        self.status: int = status


class Candidate(msgspec.Struct, frozen=True):
    guid: str
    title: str
    date: datetime


class Release(msgspec.Struct, frozen=True):
    guid: str
    title: str
    date: datetime
    size: int
    category: int
    approximate_size: bool = False


class Credentials(msgspec.Struct, frozen=True, repr_omit_defaults=True):
    base_url: str
    api_key: str
    user_id: str
    session: str

    @override
    def __repr__(self) -> str:
        return "Credentials(<redacted>)"


class Search(msgspec.Struct, frozen=True):
    mode: str = "search"
    query: str = ""
    categories: tuple[int, ...] = ()
    season: int | None = None
    episode: int | None = None


class Snapshot(msgspec.Struct, frozen=True):
    releases: tuple[Release, ...]
    scope: str
