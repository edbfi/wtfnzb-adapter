from typing import TYPE_CHECKING

import pytest

from wtfnzb_adapter.models import Credentials
from wtfnzb_adapter.session import environment
from wtfnzb_adapter.session_budget import capture_with_budget
from wtfnzb_adapter.upstream import retry_delay

if TYPE_CHECKING:
    from pathlib import Path


def test_lossless_quoted_password_and_ambiguous_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WTFNZB_PASSWORD", raising=False)
    env = tmp_path / ".env"
    _ = env.write_text('WTFNZB_PASSWORD="some#test$character"\n')
    env.chmod(0o600)
    assert environment()["WTFNZB_PASSWORD"] == "some#test$character"
    _ = env.write_text("WTFNZB_PASSWORD=some#test\n")
    with pytest.raises(ValueError, match="Quote"):
        _ = environment()
    env.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        _ = environment()


@pytest.mark.anyio
async def test_login_latch_stops_before_browser(tmp_path: Path) -> None:
    _ = (tmp_path / "login-blocked").write_text("failed")
    assert not await capture_with_budget({"ADAPTER_STATE_DIR": str(tmp_path)})
    assert not (tmp_path / "budget.json").exists()


def test_secret_repr() -> None:
    secret = Credentials("https://private.example", "secret-api", "123", "secret-cookie")
    assert "secret" not in repr(secret)


def test_retry_after_http_date_and_seconds() -> None:
    assert retry_delay("7200") == 7200
    assert retry_delay("Mon, 01 Jan 2040 00:00:00 GMT") > 3600
    assert retry_delay("nonsense") == 3600


@pytest.mark.anyio
async def test_failed_helper_latches_without_repeated_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def fail(_env: dict[str, str]) -> bool:
        calls.append(True)
        return False

    monkeypatch.setattr("wtfnzb_adapter.session_budget.capture", fail)
    env = {"ADAPTER_STATE_DIR": str(tmp_path)}
    assert not await capture_with_budget(env)
    assert (tmp_path / "login-blocked").exists()
    assert not await capture_with_budget(env)
    assert calls == [True]
