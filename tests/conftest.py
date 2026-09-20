from pathlib import Path

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def evidence() -> Path:
    return Path(__file__).resolve().parents[1] / "docs/evidence"
