import os
import re
from pathlib import Path
from typing import override
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import msgspec
from dotenv import dotenv_values

from wtfnzb_adapter.models import Credentials


class Settings(msgspec.Struct, frozen=True):
    adapter_key: str
    public_url: str
    auth_file: Path
    state_dir: Path
    timezone: ZoneInfo
    spacing: float = 10
    hourly_budget: int = 60
    daily_budget: int = 500
    archive_window: int = 5
    auto_session: bool = False

    @override
    def __repr__(self) -> str:
        return "Settings(<redacted>)"


def read_credentials(path: Path) -> Credentials:
    if path.stat().st_mode & 0o077:
        raise ValueError("Auth file must have mode 0600")
    credentials = msgspec.json.decode(path.read_bytes(), type=Credentials)
    parsed = urlsplit(credentials.base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.username is not None
        or parsed.fragment
    ):
        raise ValueError("Upstream base URL must be an HTTPS origin")
    if (
        not credentials.api_key
        or not credentials.user_id.isdecimal()
        or not re.fullmatch(r"[A-Za-z0-9,-]+", credentials.session)
    ):
        raise ValueError("Auth file is missing upstream credentials")
    return credentials


def settings_from_env() -> Settings:
    values = {**dotenv_values(".env", interpolate=False), **os.environ}

    def required(name: str) -> str:
        value = values.get(name)
        if not value:
            raise ValueError(f"Missing configuration: {name}")
        return value

    public = required("ADAPTER_PUBLIC_URL").rstrip("/")
    parsed = urlsplit(public)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.fragment
    ):
        raise ValueError("ADAPTER_PUBLIC_URL must be an HTTP(S) URL without credentials or query")
    key = required("ADAPTER_API_KEY")
    if len(key) < 24:
        raise ValueError("ADAPTER_API_KEY must contain at least 24 characters")
    return Settings(
        key,
        public,
        Path(required("WTFNZB_AUTH_FILE")).resolve(),
        Path(values.get("ADAPTER_STATE_DIR") or ".state").resolve(),
        ZoneInfo(required("WTFNZB_SITE_TIMEZONE")),
        auto_session=values.get("WTFNZB_AUTO_SESSION") == "true",
    )
