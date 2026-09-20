"""Optional local Ego Lite session capture; no password sent through HTTP guesses."""

import json
import os
import re
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path

from dotenv import dotenv_values


def environment() -> dict[str, str]:
    path = Path(".env")
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise ValueError(".env must have mode 0600 before using login credentials")
        for line in path.read_text().splitlines():
            match = re.match(r"\s*(?:export\s+)?WTFNZB_PASSWORD\s*=\s*(.*)", line)
            if match and "#" in match[1] and not match[1].startswith(("'", '"')):
                raise ValueError(
                    "Quote WTFNZB_PASSWORD; unquoted # is ambiguous. No login attempted"
                )
    return {
        **{k: v for k, v in dotenv_values(path, interpolate=False).items() if v is not None},
        **os.environ,
    }


def capture(env: dict[str, str]) -> bool:
    for name in ("WTFNZB_BASE_URL", "WTFNZB_AUTH_FILE", "ADAPTER_STATE_DIR"):
        if not env.get(name):
            raise ValueError(f"Missing session helper setting: {name}")
    env = dict(env)
    env["ADAPTER_STATE_DIR"] = str(Path(env["ADAPTER_STATE_DIR"]).resolve())
    env["WTFNZB_AUTH_FILE"] = str(Path(env["WTFNZB_AUTH_FILE"]).resolve())
    Path(env["ADAPTER_STATE_DIR"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    script = files("wtfnzb_adapter").joinpath("ego_session.mjs").read_bytes()
    # Ego's Node runtime does not inherit arbitrary CLI environment variables.
    # Transfer only required settings via an ephemeral mode-0600 local file.
    selected = {k: v for k, v in env.items() if k.startswith("WTFNZB_") or k == "ADAPTER_STATE_DIR"}
    with tempfile.NamedTemporaryFile(dir=env["ADAPTER_STATE_DIR"], suffix=".json") as handle:
        _ = handle.write(json.dumps(selected).encode())
        handle.flush()
        prefix = (
            "const helperEnv = JSON.parse(await (await import('node:fs/promises')).readFile("
            + json.dumps(handle.name)
            + ", 'utf8'));\n"
        )
        try:
            result = subprocess.run(
                ["ego-browser", "nodejs"],
                input=prefix.encode() + script,
                env={k: v for k, v in env.items() if not k.startswith(("WTFNZB_", "ADAPTER_"))},
                capture_output=True,
                timeout=75,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            return False
        return result.returncode == 0 and b"Session captured successfully" in result.stdout
