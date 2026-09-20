import os
import tempfile
from pathlib import Path

import msgspec


class Budget(msgspec.Struct):
    requests: list[float] = msgspec.field(default_factory=list)
    cooldown_until: float = 0
    auth_blocked: bool = False


def private_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            _ = handle.write(data)
        _ = temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
