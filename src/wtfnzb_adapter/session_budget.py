import asyncio
import fcntl
import time
from functools import partial
from pathlib import Path

import anyio
import msgspec

from wtfnzb_adapter.session import capture
from wtfnzb_adapter.state import Budget, private_write


async def capture_with_budget(env: dict[str, str], *, running_budget: Budget | None = None) -> bool:
    """Reserve three navigations/submission before an optional browser refresh.

    Browser subresources are not individually counted; budget units are logical
    page/API operations. The browser helper spaces these operations by 10 s.
    """
    directory = Path(env.get("ADAPTER_STATE_DIR", ".state"))
    await anyio.to_thread.run_sync(
        partial(directory.mkdir, mode=0o700, parents=True, exist_ok=True)
    )
    lock = (directory / "instance.lock").open("ab")
    try:
        if running_budget is None:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError(
                    "Stop the adapter before running standalone session capture"
                ) from None
        path = directory / "budget.json"
        budget = (
            running_budget
            if running_budget is not None
            else (
                msgspec.json.decode(path.read_bytes(), type=Budget) if path.exists() else Budget()
            )
        )
        now = time.time()
        budget.requests = [t for t in budget.requests if t > now - 86400]
        if (
            budget.cooldown_until > now
            or len(budget.requests) + 3 > 500
            or sum(t > now - 3600 for t in budget.requests) + 3 > 60
            or (directory / "login-blocked").exists()
        ):
            return False
        if budget.requests:
            await asyncio.sleep(max(0, 10 - (now - budget.requests[-1])))
        budget.requests.extend([time.time()] * 3)
        await anyio.to_thread.run_sync(private_write, path, msgspec.json.encode(budget))
        success = await anyio.to_thread.run_sync(capture, env)
        # Use completion time for subsequent spacing, including failed attempts.
        budget.requests[-1] = time.time()
        if not success:
            budget.cooldown_until = time.time() + 3600
            await anyio.to_thread.run_sync(
                private_write,
                directory / "login-blocked",
                b"Session refresh failed. Inspect Ego before resetting.\n",
            )
        await anyio.to_thread.run_sync(private_write, path, msgspec.json.encode(budget))
        return success
    finally:
        lock.close()
